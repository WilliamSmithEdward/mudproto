import asyncio
import re
import uuid

from grammar import resolve_player_pronouns, with_article
from experience import award_experience
from player_resources import roll_level_resource_gains
from assets import get_gear_template_by_id
from battle_round_ticks import process_battle_round_support_effects
from combat_abilities import (
    _entity_try_cast_spell,
    _entity_try_use_skill,
    _process_entity_battle_round_support_effects,
    cast_spell,
    process_entity_game_hour_tick,
    use_skill,
)
from combat_text import (
    append_newline_if_needed,
    build_entity_attack_parts,
    build_player_attack_parts,
)
from damage import (
    get_npc_hit_modifier,
    get_player_hit_modifier,
    resolve_weapon_verb,
    roll_hit,
    roll_npc_weapon_damage,
    roll_player_damage,
)
from equipment import get_equipped_main_hand, get_equipped_off_hand, get_player_armor_class
from inventory import build_equippable_item_from_template
from models import ClientSession, CorpseState, EntityState, ItemState
from session_registry import active_character_sessions, connected_clients
from death import build_player_death_broadcast_parts, build_player_death_mourn_parts, build_player_death_parts, handle_player_death
from settings import (
    COMBAT_ROUND_INTERVAL_SECONDS,
)
from targeting import list_room_entities, resolve_room_entity_selector


OPENING_ATTACKER_PLAYER = "player"
OPENING_ATTACKER_ENTITY = "entity"


def _session_contributor_key(session: ClientSession) -> str:
    return (session.player_state_key or session.client_id).strip().lower()


def _mark_entity_contributor(session: ClientSession, entity: EntityState) -> None:
    contributor_key = _session_contributor_key(session)
    if contributor_key:
        entity.experience_contributor_keys.add(contributor_key)


def _append_experience_gain_notification(
    session: ClientSession,
    gained: int,
    old_level: int,
    new_level: int,
    parts: list[dict],
    build_part_fn,
) -> None:
    if gained <= 0:
        return

    append_newline_if_needed(parts)
    parts.extend([
        build_part_fn("You gain ", "bright_white"),
        build_part_fn(str(gained), "bright_cyan", True),
        build_part_fn(" experience.", "bright_white"),
    ])

    if new_level > old_level:
        resource_gains = roll_level_resource_gains(session, old_level, new_level)
        append_newline_if_needed(parts)
        parts.append(build_part_fn("\n"))
        parts.extend([
            build_part_fn("You advance to level ", "bright_green", True),
            build_part_fn(str(new_level), "bright_green", True),
            build_part_fn("!", "bright_green", True),
        ])
        append_newline_if_needed(parts)
        parts.extend([
            build_part_fn("Level gains: ", "bright_white"),
            build_part_fn(f"+{int(resource_gains.get('hit_points', 0))}HP", "bright_green", True),
            build_part_fn(" ", "bright_white"),
            build_part_fn(f"+{int(resource_gains.get('vigor', 0))}V", "bright_yellow", True),
            build_part_fn(" ", "bright_white"),
            build_part_fn(f"+{int(resource_gains.get('mana', 0))}M", "bright_cyan", True),
        ])
        parts.append(build_part_fn("\n"))
    else:
        parts.append(build_part_fn("\n"))


def _iter_experience_contributor_sessions(contributor_keys: set[str], *, room_id: str) -> list[ClientSession]:
    if not contributor_keys:
        return []

    normalized_keys = {str(key).strip().lower() for key in contributor_keys if str(key).strip()}
    normalized_room_id = str(room_id).strip()
    if not normalized_keys or not normalized_room_id:
        return []

    matched_sessions: list[ClientSession] = []
    seen_keys: set[str] = set()
    for session in list(active_character_sessions.values()) + list(connected_clients.values()):
        if not session.is_authenticated:
            continue
        if str(session.player.current_room_id).strip() != normalized_room_id:
            continue
        session_key = _session_contributor_key(session)
        if not session_key or session_key not in normalized_keys or session_key in seen_keys:
            continue
        matched_sessions.append(session)
        seen_keys.add(session_key)

    return matched_sessions


def _queue_experience_gain_notification(session: ClientSession, gained: int, old_level: int, new_level: int) -> None:
    if gained <= 0:
        return

    from display import build_part, parts_to_lines

    notification_parts: list[dict] = []
    _append_experience_gain_notification(
        session,
        gained,
        old_level,
        new_level,
        notification_parts,
        build_part,
    )
    notification_lines = parts_to_lines(notification_parts)
    if not notification_lines:
        return

    if session.pending_private_lines and session.pending_private_lines[-1]:
        session.pending_private_lines.append([])
    session.pending_private_lines.extend(notification_lines)


def _award_shared_entity_experience(session: ClientSession, entity: EntityState, parts: list[dict], build_part_fn) -> None:
    if bool(getattr(entity, "experience_reward_claimed", False)):
        return

    experience_reward = max(0, int(getattr(entity, "experience_reward", 0)))
    if experience_reward <= 0:
        entity.experience_reward_claimed = True
        entity.experience_contributor_keys.clear()
        return

    contributor_keys = set(getattr(entity, "experience_contributor_keys", set()))
    current_key = _session_contributor_key(session)
    if current_key:
        contributor_keys.add(current_key)

    rewarded_keys: set[str] = set()
    for contributor_session in _iter_experience_contributor_sessions(contributor_keys, room_id=entity.room_id):
        contributor_key = _session_contributor_key(contributor_session)
        if not contributor_key or contributor_key in rewarded_keys:
            continue

        gained, old_level, new_level, _ = award_experience(contributor_session, experience_reward)
        rewarded_keys.add(contributor_key)
        _queue_experience_gain_notification(contributor_session, gained, old_level, new_level)

    if current_key and current_key not in rewarded_keys:
        gained, old_level, new_level, _ = award_experience(session, experience_reward)
        _queue_experience_gain_notification(session, gained, old_level, new_level)

    entity.experience_reward_claimed = True
    entity.experience_contributor_keys.clear()


def _attach_room_broadcast_lines(outbound: dict, lines: list[str]) -> dict:
    payload = outbound.get("payload")
    if not isinstance(payload, dict):
        return outbound

    broadcast_lines: list[list[dict]] = []
    for line in lines:
        cleaned = str(line).strip()
        if not cleaned:
            continue

        is_death_line = cleaned.lower().endswith(" is dead!")
        fg = "bright_red" if is_death_line else "bright_white"
        bold = is_death_line
        broadcast_lines.append([
            {"text": cleaned, "fg": fg, "bold": bold}
        ])

    if broadcast_lines:
        payload["room_broadcast_lines"] = broadcast_lines
    return outbound


def _render_observer_template(template_text: str, actor_name: str, actor_gender: str | None = None) -> str:
    resolved_gender = actor_gender
    if not resolved_gender:
        normalized_actor_name = actor_name.strip().lower()
        for active_session in active_character_sessions.values():
            if active_session.authenticated_character_name.strip().lower() == normalized_actor_name:
                resolved_gender = active_session.player.gender
                break

    actor_subject, actor_object, actor_possessive, _ = resolve_player_pronouns(
        actor_name=actor_name,
        actor_gender=resolved_gender,
    )
    return (
        template_text
        .replace("[actor_name]", actor_name)
        .replace("[actor_subject]", actor_subject)
        .replace("[actor_object]", actor_object)
        .replace("[actor_possessive]", actor_possessive)
    )


def _observer_context_from_player_context(context: str, target_text: str | None = None) -> str:
    if not context:
        return ""

    resolved = context
    resolved = resolved.replace("[a/an]", target_text or "the target")
    resolved = resolved.replace("[verb]", "is")
    resolved = resolved.replace(" your ", " their ")
    resolved = resolved.replace(" you ", " them ")
    resolved = resolved.replace(" yourself", " themselves")
    if resolved.startswith("Your "):
        resolved = f"Their {resolved[5:]}"
    if resolved.startswith("You "):
        resolved = f"{resolved[4:]}"
    return resolved


def _resolve_combat_context(context: str, *, target_text: str, verb: str) -> str:
    resolved = str(context).strip()
    if not resolved:
        return ""

    resolved = resolved.replace("[a/an]", target_text)
    resolved = resolved.replace("[verb]", verb)

    if target_text.strip().lower() == "you":
        resolved = re.sub(r"\byou is\b", "you are", resolved, flags=re.IGNORECASE)
        resolved = re.sub(r"\byou has\b", "you have", resolved, flags=re.IGNORECASE)
        if resolved.startswith("you "):
            resolved = f"You{resolved[3:]}"

    if resolved and not resolved.endswith("."):
        resolved += "."
    return resolved


def _default_observer_action_line(
    actor_name: str,
    action_verb: str,
    ability_name: str,
    cast_type: str,
    target_label: str | None = None,
) -> str:
    if cast_type == "self":
        return f"{actor_name} {action_verb} {ability_name} on themselves."
    if cast_type == "target" and target_label:
        return f"{actor_name} {action_verb} {ability_name} on {target_label}."
    if cast_type == "aoe":
        return f"{actor_name} {action_verb} {ability_name} across the room."
    return f"{actor_name} {action_verb} {ability_name}."


def _normalize_observer_sentence(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return ""
    if normalized[-1] not in ".!?":
        normalized += "."
    return normalized


def _resolve_observer_action_line(
    actor_name: str,
    action_verb: str,
    ability_name: str,
    cast_type: str,
    target_label: str | None = None,
    observer_action: str = "",
) -> str:
    canonical_line = _default_observer_action_line(actor_name, action_verb, ability_name, cast_type, target_label)
    rendered_custom = _normalize_observer_sentence(_render_observer_template(observer_action, actor_name))
    if not rendered_custom:
        return canonical_line

    lowered = rendered_custom.lower()

    if cast_type == "self" and "on themselves" not in lowered:
        return f"{rendered_custom.rstrip('.!?')} on themselves."

    if cast_type == "aoe" and "across the room" not in lowered:
        return f"{rendered_custom.rstrip('.!?')} across the room."

    if cast_type == "target" and target_label:
        lowered_target = target_label.lower()
        if f" on {lowered_target}" not in lowered and f" at {lowered_target}" not in lowered:
            return f"{rendered_custom.rstrip('.!?')} on {target_label}."

    return rendered_custom


def get_health_condition(hit_points: int, max_hit_points: int) -> tuple[str, str]:
    if max_hit_points <= 0:
        return "awful", "bright_red"

    ratio = max(0.0, min(1.0, hit_points / max_hit_points))
    if ratio <= 0.15:
        return "awful", "bright_red"
    if ratio <= 0.30:
        return "very poor", "bright_red"
    if ratio <= 0.45:
        return "poor", "bright_red"
    if ratio <= 0.60:
        return "average", "bright_yellow"
    if ratio <= 0.75:
        return "fair", "bright_yellow"
    if ratio <= 0.90:
        return "good", "bright_green"
    if ratio < 1.0:
        return "very good", "bright_green"
    return "perfect", "bright_green"


def get_entity_condition(entity: EntityState) -> tuple[str, str]:
    return get_health_condition(entity.hit_points, entity.max_hit_points)


def _build_player_attack_sequence(session: ClientSession, allow_off_hand: bool) -> list[ItemState | None]:
    attack_sequence: list[ItemState | None] = []

    main_hand = get_equipped_main_hand(session)
    main_weapon = main_hand if main_hand is not None and main_hand.slot == "weapon" else None

    off_hand = get_equipped_off_hand(session)
    off_weapon = off_hand if off_hand is not None and off_hand.slot == "weapon" else None
    if main_weapon is not None and off_weapon is not None and off_weapon.item_id == main_weapon.item_id:
        off_weapon = None

    attack_sequence.append(main_weapon)

    if allow_off_hand and off_weapon is not None:
        attack_sequence.append(off_weapon)

    return attack_sequence


def spawn_corpse_for_entity(session: ClientSession, entity: EntityState) -> CorpseState:
    next_spawn_sequence = max((corpse.spawn_sequence for corpse in session.corpses.values()), default=0) + 1
    session.corpse_spawn_counter = max(session.corpse_spawn_counter, next_spawn_sequence)
    corpse_id = f"corpse-{uuid.uuid4().hex[:8]}"
    loot_items: dict[str, ItemState] = {}

    equipped_template_ids: list[str] = []
    if entity.main_hand_weapon_template_id.strip():
        equipped_template_ids.append(entity.main_hand_weapon_template_id.strip())
    if entity.off_hand_weapon_template_id.strip():
        equipped_template_ids.append(entity.off_hand_weapon_template_id.strip())

    for template_id in equipped_template_ids:
        template = get_gear_template_by_id(template_id)
        if template is None:
            continue

        loot_item = build_equippable_item_from_template(template, item_id=f"loot-{uuid.uuid4().hex[:8]}")
        loot_items[loot_item.item_id] = loot_item

    for carried_item in list(getattr(entity, "inventory_items", [])) + list(getattr(entity, "loot_items", [])):
        if not isinstance(carried_item, ItemState):
            continue
        loot_items[carried_item.item_id] = carried_item

    entity.inventory_items = []
    entity.loot_items = []

    corpse = CorpseState(
        corpse_id=corpse_id,
        source_entity_id=entity.entity_id,
        source_name=entity.name,
        room_id=entity.room_id,
        coins=max(0, entity.coin_reward),
        loot_items=loot_items,
        spawn_sequence=next_spawn_sequence,
    )
    session.corpses[corpse_id] = corpse
    return corpse


def clear_combat_if_invalid(session: ClientSession) -> None:
    current_room_id = session.player.current_room_id
    invalid_entities = set()
    
    for entity_id in session.combat.engaged_entity_ids:
        entity = session.entities.get(entity_id)
        if entity is None or not entity.is_alive or entity.room_id != current_room_id:
            invalid_entities.add(entity_id)
    
    session.combat.engaged_entity_ids -= invalid_entities
    
    if not session.combat.engaged_entity_ids:
        end_combat(session)


def end_combat(session: ClientSession) -> None:
    session.combat.engaged_entity_ids.clear()
    session.combat.next_round_monotonic = None
    session.combat.opening_attacker = None


def start_combat(session: ClientSession, entity_id: str, opening_attacker: str) -> bool:
    if entity_id in session.combat.engaged_entity_ids:
        return False

    entity = session.entities.get(entity_id)
    if entity is None or not entity.is_alive:
        return False
    if bool(getattr(entity, "is_peaceful", False)):
        return False
    if entity.room_id != session.player.current_room_id:
        return False

    session.combat.engaged_entity_ids.add(entity_id)
    session.combat.next_round_monotonic = None
    if not session.combat.opening_attacker:
        session.combat.opening_attacker = opening_attacker
    return True


def _display_peaceful_warning(session: ClientSession, entity: EntityState) -> dict:
    from display import build_display, build_part, resolve_prompt

    prompt_after, prompt_parts = resolve_prompt(session, True)
    return build_display(
        [
            build_part("Relax. ", "bright_yellow", True),
            build_part(f"{entity.name} is peaceful.", "bright_white"),
        ],
        prompt_after=prompt_after,
        prompt_parts=prompt_parts,
        is_error=True,
    )


def _find_peaceful_target(
    session: ClientSession,
    *,
    target_name: str | None = None,
    include_room_scan: bool = False,
) -> EntityState | None:
    if target_name:
        entity, _ = resolve_room_entity_selector(
            session,
            session.player.current_room_id,
            target_name,
            living_only=True,
        )
        if entity is not None and bool(getattr(entity, "is_peaceful", False)):
            return entity

    if include_room_scan:
        for entity in list_room_entities(session, session.player.current_room_id):
            if entity.is_alive and bool(getattr(entity, "is_peaceful", False)):
                return entity

    return None


def _schedule_next_combat_round(session: ClientSession) -> None:
    try:
        now = asyncio.get_running_loop().time()
    except RuntimeError:
        session.combat.next_round_monotonic = None
        return

    session.combat.next_round_monotonic = now + COMBAT_ROUND_INTERVAL_SECONDS


def get_engaged_entities(session: ClientSession) -> list[EntityState]:
    clear_combat_if_invalid(session)

    entities = []
    for entity_id in session.combat.engaged_entity_ids:
        entity = session.entities.get(entity_id)
        if entity is not None:
            entities.append(entity)
    entities.sort(key=lambda item: item.spawn_sequence)
    return entities


def get_engaged_entity(session: ClientSession) -> EntityState | None:
    """Get primary engaged entity (first in set for player attacks)."""
    entities = get_engaged_entities(session)
    return entities[0] if entities else None


def _engage_next_targeting_entity(
    session: ClientSession,
    defeated_entity_id: str,
    active_target_entity_ids: set[str] | None = None,
) -> EntityState | None:
    """Select next target only from entities currently engaging this player."""
    candidates: list[EntityState] = []
    for candidate in get_engaged_entities(session):
        if candidate.entity_id == defeated_entity_id:
            continue
        if not candidate.is_alive:
            continue
        if active_target_entity_ids is not None and candidate.entity_id not in active_target_entity_ids:
            continue
        candidates.append(candidate)

    if candidates:
        next_target = candidates[0]
        session.combat.opening_attacker = None
        _schedule_next_combat_round(session)
        return next_target

    end_combat(session)
    return None


def _decrement_cooldowns(cooldowns: dict[str, int]) -> None:
    for key in list(cooldowns.keys()):
        remaining = int(cooldowns.get(key, 0))
        if remaining <= 1:
            cooldowns.pop(key, None)
        else:
            cooldowns[key] = remaining - 1


def _process_combat_round_timers(session: ClientSession, entities: list[EntityState]) -> None:
    _decrement_cooldowns(session.combat.skill_cooldowns)
    _decrement_cooldowns(session.combat.item_cooldowns)

    for entity in entities:
        _process_entity_battle_round_support_effects(entity)
        _decrement_cooldowns(entity.skill_cooldowns)
        _decrement_cooldowns(entity.spell_cooldowns)


def _consume_entity_action_lag(entity: EntityState) -> bool:
    if entity.skill_lag_rounds_remaining > 0:
        entity.skill_lag_rounds_remaining -= 1
    if entity.spell_lag_rounds_remaining <= 0:
        return False
    entity.spell_lag_rounds_remaining -= 1
    return True


def tick_out_of_combat_cooldowns(session: ClientSession) -> None:
    """Decrement player combat-tracked cooldowns for sessions not currently in combat."""
    _decrement_cooldowns(session.combat.skill_cooldowns)
    _decrement_cooldowns(session.combat.item_cooldowns)


def _is_entity_engaged_by_other_player(entity_id: str, current_session: ClientSession) -> bool:
    """Check if an entity is already engaged by any other player."""
    # Check connected clients
    for sess in connected_clients.values():
        if sess != current_session and entity_id in sess.combat.engaged_entity_ids:
            return True
    
    # Check active character sessions (including offline characters)
    for sess in active_character_sessions.values():
        if sess != current_session and entity_id in sess.combat.engaged_entity_ids:
            return True
    
    return False


def maybe_auto_engage_current_room(session: ClientSession) -> list[EntityState]:
    clear_combat_if_invalid(session)
    if session.combat.engaged_entity_ids:
        return []

    engaged_entities = []
    room_entities = list_room_entities(session, session.player.current_room_id)
    for entity in room_entities:
        if entity.is_aggro and not _is_entity_engaged_by_other_player(entity.entity_id, session):
            started = start_combat(session, entity.entity_id, OPENING_ATTACKER_ENTITY)
            if started:
                engaged_entities.append(entity)

    return engaged_entities


def begin_attack(session: ClientSession, target_name: str) -> dict | list[dict]:
    from display import display_error, display_force_prompt

    clear_combat_if_invalid(session)
    entity, resolve_error = resolve_room_entity_selector(
        session,
        session.player.current_room_id,
        target_name,
        living_only=True,
    )

    if entity is None:
        return display_error(resolve_error or f"No target named '{target_name}' is here.", session)
    if bool(getattr(entity, "is_peaceful", False)):
        return _display_peaceful_warning(session, entity)

    started = start_combat(session, entity.entity_id, OPENING_ATTACKER_PLAYER)
    if not started:
        return display_error(f"{entity.name} is already engaged with another target.", session)

    immediate_round = resolve_combat_round(session)
    if immediate_round is not None:
        if session.pending_death_logout:
            return immediate_round
        return [immediate_round, display_force_prompt(session)]

    return display_error(f"You fail to engage {entity.name}.", session)


def _apply_player_attacks(session: ClientSession, entity: EntityState, parts: list[dict], allow_off_hand: bool) -> None:
    attack_sequence = _build_player_attack_sequence(session, allow_off_hand)

    for weapon in attack_sequence:
        if not entity.is_alive:
            break

        append_newline_if_needed(parts)

        hit_modifier = get_player_hit_modifier(weapon, player_level=session.player.level)
        if not roll_hit(hit_modifier, entity.armor_class):
            miss_verb = resolve_weapon_verb(weapon.weapon_type) if weapon is not None else "hit"
            parts.extend(build_player_attack_parts(
                entity_name=entity.name,
                attack_verb=miss_verb,
                damage=0,
                target_max_hp=entity.max_hit_points,
            ))
            continue

        rolled_damage, weapon_name, attack_verb = roll_player_damage(
            session.player_combat,
            weapon,
            player_level=session.player.level,
        )
        _mark_entity_contributor(session, entity)
        entity.hit_points = max(0, entity.hit_points - rolled_damage)
        parts.extend(build_player_attack_parts(
            entity_name=entity.name,
            attack_verb=attack_verb,
            damage=rolled_damage,
            target_max_hp=entity.max_hit_points,
        ))

        if entity.hit_points <= 0:
            break


def _apply_entity_attacks(session: ClientSession, attacker: EntityState, parts: list[dict], allow_off_hand: bool) -> None:
    status = session.status
    player_armor_class = get_player_armor_class(session)

    def _resolve_npc_weapon_template(template_id: str) -> dict | None:
        normalized_template_id = template_id.strip()
        if not normalized_template_id:
            return None
        template = get_gear_template_by_id(normalized_template_id)
        if template is None:
            return None
        if str(template.get("slot", "")).strip().lower() != "weapon":
            return None
        return template

    entity = attacker
    if not entity.is_alive:
        return

    if _consume_entity_action_lag(entity):
        return

    # Allow at most one special action (spell or skill) per round.
    # Keep existing priority: try spell first, then skill if no spell fired.
    casted_spell = _entity_try_cast_spell(session, entity, parts)
    if not casted_spell:
        _entity_try_use_skill(session, entity, parts)

    main_hand_weapon = _resolve_npc_weapon_template(entity.main_hand_weapon_template_id)
    off_hand_weapon = _resolve_npc_weapon_template(entity.off_hand_weapon_template_id)

    for _ in range(max(1, entity.attacks_per_round)):
        append_newline_if_needed(parts)

        main_hit_modifier = get_npc_hit_modifier(entity, main_hand_weapon, off_hand=False)
        if not roll_hit(main_hit_modifier, player_armor_class):
            miss_verb = (
                resolve_weapon_verb(str(main_hand_weapon.get("weapon_type", "unarmed")))
                if main_hand_weapon is not None
                else "hit"
            )
            parts.extend(build_entity_attack_parts(
                entity_name=entity.name,
                entity_pronoun_possessive=entity.pronoun_possessive,
                attack_verb=miss_verb,
                damage=0,
            ))
            continue

        attack_damage, attack_verb = roll_npc_weapon_damage(entity, main_hand_weapon)
        status.hit_points = max(0, status.hit_points - attack_damage)
        parts.extend(build_entity_attack_parts(
            entity_name=entity.name,
            entity_pronoun_possessive=entity.pronoun_possessive,
            attack_verb=attack_verb,
            damage=attack_damage,
        ))
        if status.hit_points <= 0:
            return

    if allow_off_hand:
        off_hand_swings = max(0, entity.off_hand_attacks_per_round)
        for _ in range(off_hand_swings):
            if status.hit_points <= 0:
                return
            append_newline_if_needed(parts)

            off_hit_modifier = get_npc_hit_modifier(entity, off_hand_weapon, off_hand=True)
            if not roll_hit(off_hit_modifier, player_armor_class):
                miss_verb = (
                    resolve_weapon_verb(str(off_hand_weapon.get("weapon_type", "unarmed")))
                    if off_hand_weapon is not None
                    else "hit"
                )
                parts.extend(build_entity_attack_parts(
                    entity_name=entity.name,
                    entity_pronoun_possessive=entity.pronoun_possessive,
                    attack_verb=miss_verb,
                    damage=0,
                ))
                continue

            off_hand_damage, off_attack_verb = roll_npc_weapon_damage(entity, off_hand_weapon)
            status.hit_points = max(0, status.hit_points - off_hand_damage)
            parts.extend(build_entity_attack_parts(
                entity_name=entity.name,
                entity_pronoun_possessive=entity.pronoun_possessive,
                attack_verb=off_attack_verb,
                damage=off_hand_damage,
            ))
            if status.hit_points <= 0:
                return


def resolve_combat_round(
    session: ClientSession,
    *,
    allowed_entity_retaliation_ids: set[str] | None = None,
) -> dict | None:
    from display import build_part, display_combat_round_result

    clear_combat_if_invalid(session)

    engaged_entities = get_engaged_entities(session)
    if not engaged_entities:
        return None

    entity = engaged_entities[0]  # Primary target for melee combat
    if entity is None or not entity.is_alive or entity.room_id != session.player.current_room_id:
        clear_combat_if_invalid(session)
        return None

    process_battle_round_support_effects(session)

    parts: list[dict] = []
    status = session.status
    opening_attacker = session.combat.opening_attacker
    is_opening_round = opening_attacker is not None
    _process_combat_round_timers(session, engaged_entities)

    retaliating_entities = [
        engaged
        for engaged in engaged_entities
        if allowed_entity_retaliation_ids is None or engaged.entity_id in allowed_entity_retaliation_ids
    ]

    if opening_attacker == OPENING_ATTACKER_ENTITY:
        for retaliating_entity in retaliating_entities:
            _apply_entity_attacks(session, retaliating_entity, parts, allow_off_hand=False)
            if status.hit_points <= 0:
                break
    else:
        if session.combat.skip_melee_rounds > 0:
            session.combat.skip_melee_rounds -= 1
        else:
            _apply_player_attacks(session, entity, parts, allow_off_hand=not is_opening_round)

    # Mark entity dead if it reached 0 HP, but don't return yet — let the round finish.
    entity_died_this_round = False
    if entity.hit_points <= 0:
        entity_died_this_round = True
        if entity.is_alive:
            entity.is_alive = False
        spawn_corpse_for_entity(session, entity)
        _award_shared_entity_experience(session, entity, parts, build_part)

    # Announce entity death immediately after the lethal hit is resolved.
    if entity_died_this_round:
        append_newline_if_needed(parts)
        parts.extend([
            build_part(with_article(entity.name, capitalize=True), "bright_red", True),
            build_part(" is dead!", "bright_red", True),
        ])

        if entity.entity_id in session.combat.engaged_entity_ids:
            session.combat.engaged_entity_ids.discard(entity.entity_id)
            next_target = _engage_next_targeting_entity(
                session,
                entity.entity_id,
                active_target_entity_ids=allowed_entity_retaliation_ids,
            )
            if next_target is not None:
                append_newline_if_needed(parts)
                parts.extend([
                    build_part("You turn to ", "bright_white"),
                    build_part(with_article(next_target.name)),
                    build_part(".", "bright_white"),
                ])

    # Continue retaliation phase after player-side output has been assembled.
    if opening_attacker is not None:
        session.combat.opening_attacker = None
    else:
        current_engaged_entities = get_engaged_entities(session)
        current_retaliating_entities = [
            engaged
            for engaged in current_engaged_entities
            if allowed_entity_retaliation_ids is None or engaged.entity_id in allowed_entity_retaliation_ids
        ]
        for retaliating_entity in current_retaliating_entities:
            _apply_entity_attacks(session, retaliating_entity, parts, allow_off_hand=True)
            if status.hit_points <= 0:
                break

    # Now display player death if it occurred this round.

    if status.hit_points <= 0:
        handle_player_death(session)

        append_newline_if_needed(parts)
        parts.extend(build_player_death_parts())
        parts.extend(build_player_death_mourn_parts())

        result = display_combat_round_result(session, parts)
        payload = result.get("payload") if isinstance(result, dict) else None
        if isinstance(payload, dict):
            actor_name = session.authenticated_character_name or "Someone"
            room_broadcast_lines: list[list[dict]] = []
            if entity_died_this_round:
                room_broadcast_lines.append([
                    build_part(with_article(entity.name, capitalize=True), "bright_red", True),
                    build_part(" is dead!", "bright_red", True),
                ])
            room_broadcast_lines.append(build_player_death_broadcast_parts(actor_name))
            payload["room_broadcast_lines"] = room_broadcast_lines

        return result

    if entity_died_this_round:
        return display_combat_round_result(session, parts)

    _schedule_next_combat_round(session)
    return display_combat_round_result(session, parts)