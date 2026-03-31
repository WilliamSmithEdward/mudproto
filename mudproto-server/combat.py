import asyncio
import random
import re
import uuid

from assets import get_equipment_template_by_id, get_npc_template_by_id, get_skill_by_id
from battle_round_ticks import process_battle_round_support_effects
from combat_text import (
    append_newline_if_needed,
    build_entity_attack_parts,
    build_player_attack_parts,
    with_article,
)
from damage import (
    get_npc_hit_modifier,
    get_player_hit_modifier,
    resolve_weapon_verb,
    roll_hit,
    roll_npc_weapon_damage,
    roll_player_damage,
    roll_skill_damage,
    roll_spell_damage,
)
from equipment import get_equipped_main_hand, get_equipped_off_hand, get_player_armor_class
from models import ActiveSupportEffectState, ClientSession, CorpseState, EntityState, EquipmentItemState, LootItemState
from sessions import active_character_sessions, connected_clients
from settings import (
    COMBAT_ROUND_INTERVAL_SECONDS,
    PLAYER_REFERENCE_MAX_HP,
    PLAYER_REFERENCE_MAX_MANA,
    PLAYER_REFERENCE_MAX_VIGOR,
)
from world import WORLD


OPENING_ATTACKER_PLAYER = "player"
OPENING_ATTACKER_ENTITY = "entity"


def _attach_room_broadcast_parts(outbound: dict, lines: list[str]) -> dict:
    payload = outbound.get("payload")
    if not isinstance(payload, dict):
        return outbound

    parts: list[dict] = []
    for index, line in enumerate(lines):
        cleaned = str(line).strip()
        if not cleaned:
            continue
        if index > 0 and parts:
            parts.append({"text": "\n", "fg": "bright_white", "bold": False})
        parts.append({"text": cleaned, "fg": "bright_white", "bold": False})

    if parts:
        payload["room_broadcast_parts"] = parts
    return outbound


def _render_observer_template(template_text: str, actor_name: str) -> str:
    actor_object = "them"
    actor_possessive = "their"
    actor_subject = actor_name
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


def list_room_entities(session: ClientSession, room_id: str) -> list[EntityState]:
    entities: list[EntityState] = []

    for entity in session.entities.values():
        if entity.is_alive and entity.room_id == room_id:
            entities.append(entity)

    entities.sort(key=lambda item: item.spawn_sequence)
    return entities


def list_room_corpses(session: ClientSession, room_id: str) -> list[CorpseState]:
    corpses: list[CorpseState] = []

    for corpse in session.corpses.values():
        if corpse.room_id == room_id:
            corpses.append(corpse)

    corpses.sort(key=lambda item: item.spawn_sequence)
    return corpses


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


def _build_player_attack_sequence(session: ClientSession, allow_off_hand: bool) -> list[EquipmentItemState | None]:
    attack_sequence: list[EquipmentItemState | None] = []

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


def _entity_name_keywords(name: str) -> set[str]:
    return {token for token in re.findall(r"[a-zA-Z0-9]+", name.lower()) if token}


def _corpse_keywords(corpse: CorpseState) -> set[str]:
    keywords = _entity_name_keywords(corpse.source_name)
    keywords.add("corpse")
    return keywords


def _corpse_item_keywords(item: LootItemState) -> set[str]:
    return {token for token in re.findall(r"[a-zA-Z0-9]+", item.name.lower()) if token}


def resolve_room_entity_selector(
    session: ClientSession,
    room_id: str,
    selector_text: str,
    *,
    living_only: bool = False,
) -> tuple[EntityState | None, str | None]:
    normalized = selector_text.strip().lower()
    if not normalized:
        return None, "Provide a target selector."

    all_room_entities = [
        entity
        for entity in session.entities.values()
        if entity.room_id == room_id
    ]
    all_room_entities.sort(key=lambda item: item.spawn_sequence)

    room_entities = [
        entity
        for entity in all_room_entities
        if entity.is_alive or not living_only
    ]

    # Backward-compatible free text lookup for plain names.
    if "." not in normalized:
        exact_match: EntityState | None = None
        partial_match: EntityState | None = None
        for entity in room_entities:
            entity_name = entity.name.lower()
            if entity_name == normalized:
                exact_match = entity
                break
            if normalized in entity_name and partial_match is None:
                partial_match = entity
        if exact_match is not None:
            return exact_match, None
        if partial_match is not None:
            return partial_match, None
        return None, f"No target named '{selector_text}' is here."

    parts = [part for part in normalized.split(".") if part]
    if not parts:
        return None, "Provide a target selector."

    requested_index: int | None = None
    if parts[0].isdigit():
        requested_index = int(parts[0])
        parts = parts[1:]
        if requested_index <= 0:
            return None, "Selector index must be 1 or greater."

    if not parts:
        return None, "Provide at least one selector keyword after the index."

    all_matches: list[EntityState] = []
    for entity in all_room_entities:
        keywords = _entity_name_keywords(entity.name)
        if all(keyword in keywords for keyword in parts):
            all_matches.append(entity)

    matches: list[EntityState] = []
    for entity in room_entities:
        keywords = _entity_name_keywords(entity.name)
        if all(keyword in keywords for keyword in parts):
            matches.append(entity)

    if not matches:
        if living_only and all_matches:
            return None, "All matching targets are dead."
        return None, f"No target named '{selector_text}' is here."

    if requested_index is not None:
        if requested_index > len(matches):
            if living_only and requested_index <= len(all_matches):
                indexed_target = all_matches[requested_index - 1]
                if not indexed_target.is_alive:
                    return None, f"{indexed_target.name} is already dead."
            living_label = " living" if living_only else ""
            return None, f"Only {len(matches)}{living_label} match(es) found for '{selector_text}'."
        return matches[requested_index - 1], None

    return matches[0], None


def resolve_room_corpse_selector(
    session: ClientSession,
    room_id: str,
    selector_text: str,
) -> tuple[CorpseState | None, str | None]:
    normalized = selector_text.strip().lower()
    if not normalized:
        return None, "Provide a corpse selector."

    room_corpses = list_room_corpses(session, room_id)
    if not room_corpses:
        return None, "There are no corpses here."

    if "." not in normalized:
        if normalized == "corpse":
            return room_corpses[0], None

        exact_match: CorpseState | None = None
        partial_match: CorpseState | None = None
        for corpse in room_corpses:
            corpse_name = f"{corpse.source_name} corpse".lower()
            if corpse_name == normalized:
                exact_match = corpse
                break
            if normalized in corpse_name and partial_match is None:
                partial_match = corpse
        if exact_match is not None:
            return exact_match, None
        if partial_match is not None:
            return partial_match, None
        return None, f"No corpse matching '{selector_text}' is here."

    parts = [part for part in normalized.split(".") if part]
    if not parts:
        return None, "Provide a corpse selector."

    requested_index: int | None = None
    if parts[0].isdigit():
        requested_index = int(parts[0])
        parts = parts[1:]
        if requested_index <= 0:
            return None, "Selector index must be 1 or greater."

    if not parts:
        return None, "Provide at least one selector keyword after the index."

    matches: list[CorpseState] = []
    for corpse in room_corpses:
        keywords = _corpse_keywords(corpse)
        if all(keyword in keywords for keyword in parts):
            matches.append(corpse)

    if not matches:
        return None, f"No corpse matching '{selector_text}' is here."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} corpse match(es) found for '{selector_text}'."
        return matches[requested_index - 1], None

    return matches[0], None


def resolve_corpse_item_selector(corpse: CorpseState, selector_text: str) -> tuple[LootItemState | None, str | None]:
    normalized = selector_text.strip().lower()
    if not normalized:
        return None, "Provide an item selector."

    items = list(corpse.loot_items.values())
    if not items:
        return None, "That corpse has no lootable items."

    items.sort(key=lambda item: item.name.lower())

    if "." not in normalized:
        exact_match: LootItemState | None = None
        partial_match: LootItemState | None = None
        for item in items:
            item_name = item.name.lower()
            if item_name == normalized:
                exact_match = item
                break
            if normalized in item_name and partial_match is None:
                partial_match = item
        if exact_match is not None:
            return exact_match, None
        if partial_match is not None:
            return partial_match, None
        return None, f"No item matching '{selector_text}' is on that corpse."

    parts = [part for part in normalized.split(".") if part]
    if not parts:
        return None, "Provide an item selector."

    requested_index: int | None = None
    if parts[0].isdigit():
        requested_index = int(parts[0])
        parts = parts[1:]
        if requested_index <= 0:
            return None, "Selector index must be 1 or greater."

    if not parts:
        return None, "Provide at least one selector keyword after the index."

    matches: list[LootItemState] = []
    for item in items:
        keywords = _corpse_item_keywords(item)
        if all(keyword in keywords for keyword in parts):
            matches.append(item)

    if not matches:
        return None, f"No item matching '{selector_text}' is on that corpse."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} item match(es) found for '{selector_text}'."
        return matches[requested_index - 1], None

    return matches[0], None


def spawn_corpse_for_entity(session: ClientSession, entity: EntityState) -> CorpseState:
    next_spawn_sequence = max((corpse.spawn_sequence for corpse in session.corpses.values()), default=0) + 1
    session.corpse_spawn_counter = max(session.corpse_spawn_counter, next_spawn_sequence)
    corpse_id = f"corpse-{uuid.uuid4().hex[:8]}"
    loot_items: dict[str, LootItemState] = {}

    equipped_template_ids: list[str] = []
    if entity.main_hand_weapon_template_id.strip():
        equipped_template_ids.append(entity.main_hand_weapon_template_id.strip())
    if entity.off_hand_weapon_template_id.strip():
        equipped_template_ids.append(entity.off_hand_weapon_template_id.strip())

    for template_id in equipped_template_ids:
        template = get_equipment_template_by_id(template_id)
        if template is None:
            continue

        loot_item = LootItemState(
            item_id=f"loot-{uuid.uuid4().hex[:8]}",
            name=str(template.get("name", "Loot")).strip() or "Loot",
            template_id=str(template.get("template_id", "")).strip(),
            description=str(template.get("description", "")),
            keywords=[str(keyword).strip().lower() for keyword in template.get("keywords", []) if str(keyword).strip()],
        )
        loot_items[loot_item.item_id] = loot_item

    # Backward-compatible fallback for entities without equipped template-backed items.
    if not loot_items:
        loot_items = {
            item.item_id: LootItemState(
                item_id=item.item_id,
                name=item.name,
                description=item.description,
                keywords=list(item.keywords),
            )
            for item in entity.loot_items
        }
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


def find_room_entity_by_name(session: ClientSession, room_id: str, search_text: str) -> EntityState | None:
    entity, _ = resolve_room_entity_selector(session, room_id, search_text, living_only=True)
    return entity


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
    if entity.room_id != session.player.current_room_id:
        return False

    session.combat.engaged_entity_ids.add(entity_id)
    session.combat.next_round_monotonic = None
    if not session.combat.opening_attacker:
        session.combat.opening_attacker = opening_attacker
    return True


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

    for entity in entities:
        _decrement_cooldowns(entity.skill_cooldowns)
        if entity.skill_lag_rounds_remaining > 0:
            entity.skill_lag_rounds_remaining -= 1


def _resolve_player_skill_scale_bonus(session: ClientSession, skill: dict) -> int:
    scaling_attribute_id = str(skill.get("scaling_attribute_id", "")).strip().lower()
    scaling_multiplier = max(0.0, float(skill.get("scaling_multiplier", 0.0)))
    if not scaling_attribute_id or scaling_multiplier <= 0:
        return 0

    attribute_value = int(session.player.attributes.get(scaling_attribute_id, 0))
    return max(0, int(attribute_value * scaling_multiplier))


def _resolve_entity_skill_scale_bonus(entity: EntityState, skill: dict) -> int:
    scaling_multiplier = max(0.0, float(skill.get("scaling_multiplier", 0.0)))
    if scaling_multiplier <= 0:
        return 0

    return max(0, int(max(0, entity.power_level) * scaling_multiplier))


def _set_player_skill_cooldown(session: ClientSession, skill: dict) -> None:
    cooldown_rounds = max(0, int(skill.get("cooldown_rounds", 0)))
    if cooldown_rounds > 0:
        skill_id = str(skill.get("skill_id", "")).strip()
        if skill_id:
            session.combat.skill_cooldowns[skill_id] = cooldown_rounds


def _set_entity_skill_cooldown(entity: EntityState, skill: dict) -> None:
    cooldown_rounds = max(0, int(skill.get("cooldown_rounds", 0)))
    if cooldown_rounds > 0:
        skill_id = str(skill.get("skill_id", "")).strip()
        if skill_id:
            entity.skill_cooldowns[skill_id] = cooldown_rounds


def _apply_player_skill_lag(session: ClientSession, skill: dict) -> None:
    # Lag is tracked for visual feedback but doesn't skip melee rounds.
    # Skills have lag_rounds but this doesn't prevent player melee attacks.
    pass


def _apply_entity_skill_lag(entity: EntityState, skill: dict) -> None:
    lag_rounds = max(0, int(skill.get("lag_rounds", 0)))
    if lag_rounds > 0:
        entity.skill_lag_rounds_remaining = max(entity.skill_lag_rounds_remaining, lag_rounds)


def use_skill(session: ClientSession, skill: dict, target_name: str | None = None) -> tuple[dict, bool]:
    from display import build_part, display_command_result, display_error

    skill_id = str(skill.get("skill_id", "")).strip()
    skill_name = str(skill.get("name", "Skill")).strip() or "Skill"
    vigor_cost = max(0, int(skill.get("vigor_cost", 0)))
    usable_out_of_combat = bool(skill.get("usable_out_of_combat", False))
    skill_type = str(skill.get("skill_type", "damage")).strip().lower() or "damage"
    cast_type = str(skill.get("cast_type", "target")).strip().lower() or "target"
    damage_context = str(skill.get("damage_context", "")).strip()
    support_effect = str(skill.get("support_effect", "")).strip().lower()
    support_amount = max(0, int(skill.get("support_amount", 0)))
    support_context = str(skill.get("support_context", "")).strip()
    observer_action = str(skill.get("observer_action", "")).strip()
    observer_context = str(skill.get("observer_context", "")).strip()
    scaling_bonus = _resolve_player_skill_scale_bonus(session, skill)
    actor_name = session.authenticated_character_name or "Someone"

    if skill_id and session.combat.skill_cooldowns.get(skill_id, 0) > 0:
        return display_error(
            f"{skill_name} is on cooldown for {session.combat.skill_cooldowns[skill_id]} more round(s).",
            session,
        ), False

    if get_engaged_entity(session) is None and not usable_out_of_combat:
        return display_error(f"{skill_name} can only be used while in combat.", session), False

    if cast_type not in {"self", "target", "aoe"}:
        return display_error(f"Skill '{skill_name}' has unsupported cast_type '{cast_type}'.", session), False
    if skill_type not in {"damage", "support"}:
        return display_error(f"Skill '{skill_name}' has unsupported skill_type '{skill_type}'.", session), False

    description = str(skill.get("description", "")).strip()
    
    target_text = ""
    if cast_type == "target" and target_name:
        # Find the entity to get proper article format
        target_entity, _ = resolve_room_entity_selector(
            session,
            session.player.current_room_id,
            target_name,
            living_only=True,
        )
        if target_entity:
            target_text = f" on {with_article(target_entity.name)}"
        else:
            target_text = f" on {target_name}"
    elif cast_type == "self":
        target_text = " on yourself"

    parts = [
        build_part("You use "),
        build_part(skill_name),
        build_part(target_text + "."),
    ]
    if description:
        parts.extend([
            build_part("\n"),
            build_part(description),
        ])

    if skill_type == "support":
        if cast_type != "self":
            return display_error(f"Support skill '{skill_name}' must be cast_type 'self'.", session), False
        if support_effect not in {"heal", "vigor", "mana"}:
            return display_error(
                f"Skill '{skill_name}' has unsupported support_effect '{support_effect}'.",
                session,
            ), False

        if session.status.vigor < vigor_cost:
            return display_error(
                f"Not enough vigor for {skill_name}. Need {vigor_cost}V, have {session.status.vigor}V.",
                session,
            ), False

        session.status.vigor -= vigor_cost

        total_support_amount = max(0, support_amount + scaling_bonus)

        if support_effect == "heal":
            session.status.hit_points = min(PLAYER_REFERENCE_MAX_HP, session.status.hit_points + total_support_amount)
        elif support_effect == "vigor":
            session.status.vigor = min(PLAYER_REFERENCE_MAX_VIGOR, session.status.vigor + total_support_amount)
        else:
            session.status.mana = min(PLAYER_REFERENCE_MAX_MANA, session.status.mana + total_support_amount)

        if support_context:
            parts.extend([
                build_part("\n"),
                build_part(support_context),
            ])

        _set_player_skill_cooldown(session, skill)
        _apply_player_skill_lag(session, skill)
        observer_lines = [
            _render_observer_template(observer_action, actor_name) if observer_action else f"{actor_name} uses {skill_name}.",
        ]
        support_observer_context = observer_context or _observer_context_from_player_context(support_context)
        if support_observer_context:
            observer_lines.append(_render_observer_template(support_observer_context, actor_name))

        result = display_command_result(session, parts)
        return _attach_room_broadcast_parts(result, observer_lines), True

    clear_combat_if_invalid(session)

    damage_targets: list[EntityState] = []
    if cast_type == "target":
        entity: EntityState | None = None
        if target_name:
            entity, resolve_error = resolve_room_entity_selector(
                session,
                session.player.current_room_id,
                target_name,
                living_only=True,
            )
            if entity is None:
                return display_error(resolve_error or f"No target named '{target_name}' is here.", session), False
        else:
            entity = get_engaged_entity(session)
            if entity is None:
                return display_error("Target skill requires a target: skill <name> <target>", session), False
        damage_targets.append(entity)
    elif cast_type == "aoe":
        for entity in list_room_entities(session, session.player.current_room_id):
            if entity.is_alive and not entity.is_ally:
                damage_targets.append(entity)
        if not damage_targets:
            return display_error("No valid hostile targets in the room.", session), False
    else:
        return display_error(f"Damage skill '{skill_name}' cannot be cast as '{cast_type}'.", session), False

    if session.status.vigor < vigor_cost:
        return display_error(
            f"Not enough vigor for {skill_name}. Need {vigor_cost}V, have {session.status.vigor}V.",
            session,
        ), False

    session.status.vigor -= vigor_cost

    total_damage = roll_skill_damage(skill) + scaling_bonus
    destroyed_entity_names: list[str] = []

    for entity in damage_targets:
        parts.append(build_part("\n"))
        named_target = with_article(entity.name, capitalize=True)
        resolved_context = damage_context.replace("[a/an]", named_target).replace("[verb]", "is")
        if resolved_context and not resolved_context.endswith("."):
            resolved_context += "."

        if total_damage > 0:
            entity.hit_points = max(0, entity.hit_points - total_damage)
            if resolved_context:
                parts.append(build_part(resolved_context))
            else:
                parts.extend([
                    build_part(named_target),
                    build_part(" is struck by "),
                    build_part(skill_name),
                    build_part("."),
                ])
        else:
            parts.extend([
                build_part(named_target),
                build_part(" avoids "),
                build_part(skill_name),
                build_part("."),
            ])

        if entity.hit_points <= 0:
            entity.is_alive = False
            spawn_corpse_for_entity(session, entity)
            destroyed_entity_names.append(entity.name)
            parts.extend([
                build_part("\n"),
                build_part(with_article(entity.name, capitalize=True)),
                build_part(" is destroyed."),
            ])

            if entity.entity_id in session.combat.engaged_entity_ids:
                session.combat.engaged_entity_ids.discard(entity.entity_id)
                next_target = _engage_next_targeting_entity(session, entity.entity_id)
                if next_target is not None:
                    parts.extend([
                        build_part("\n"),
                        build_part("You turn to "),
                        build_part(with_article(next_target.name)),
                        build_part("."),
                    ])

    _set_player_skill_cooldown(session, skill)
    _apply_player_skill_lag(session, skill)
    target_label = with_article(damage_targets[0].name, capitalize=True) if damage_targets else None
    observer_lines = [
        _render_observer_template(observer_action, actor_name) if observer_action else f"{actor_name} uses {skill_name}.",
    ]
    damage_observer_context = observer_context or _observer_context_from_player_context(damage_context, target_label)
    if damage_observer_context:
        observer_lines.append(_render_observer_template(damage_observer_context, actor_name))
    for destroyed_name in destroyed_entity_names:
        observer_lines.append(f"{with_article(destroyed_name, capitalize=True)} is destroyed.")

    result = display_command_result(session, parts)
    return _attach_room_broadcast_parts(result, observer_lines), True


def _entity_try_use_skill(session: ClientSession, entity: EntityState, parts: list[dict]) -> bool:
    from display import build_part

    if not entity.skill_ids:
        return False

    chance = max(0.0, min(1.0, float(entity.skill_use_chance)))
    if random.random() >= chance:
        return False

    available_skills: list[dict] = []
    for skill_id in entity.skill_ids:
        skill = get_skill_by_id(skill_id)
        if skill is None:
            continue
        normalized_skill_id = str(skill.get("skill_id", "")).strip()
        if normalized_skill_id and entity.skill_cooldowns.get(normalized_skill_id, 0) > 0:
            continue
        available_skills.append(skill)

    if not available_skills:
        return False

    skill = random.choice(available_skills)
    skill_name = str(skill.get("name", "Skill")).strip() or "Skill"
    skill_type = str(skill.get("skill_type", "damage")).strip().lower() or "damage"
    cast_type = str(skill.get("cast_type", "target")).strip().lower() or "target"
    scaling_bonus = _resolve_entity_skill_scale_bonus(entity, skill)

    description = str(skill.get("description", "")).strip()
    
    append_newline_if_needed(parts)
    parts.extend([
        build_part(with_article(entity.name, capitalize=True)),
        build_part(" uses "),
        build_part(skill_name),
        build_part(" on you!"),
    ])
    if description:
        parts.extend([
            build_part(" "),
            build_part(description),
        ])

    if skill_type == "support" and cast_type == "self":
        support_effect = str(skill.get("support_effect", "")).strip().lower()
        support_amount = max(0, int(skill.get("support_amount", 0)))
        support_context = str(skill.get("support_context", "")).strip()
        total_support_amount = max(0, support_amount + scaling_bonus)

        if support_effect == "heal":
            entity.hit_points = min(entity.max_hit_points, entity.hit_points + total_support_amount)
        if support_context:
            append_newline_if_needed(parts)
            parts.append(build_part(support_context))

        _set_entity_skill_cooldown(entity, skill)
        _apply_entity_skill_lag(entity, skill)
        return True

    if skill_type == "damage" and cast_type in {"target", "aoe"}:
        total_damage = roll_skill_damage(skill) + scaling_bonus
        damage_context = str(skill.get("damage_context", "")).strip()

        if total_damage > 0:
            session.status.hit_points = max(0, session.status.hit_points - total_damage)

        append_newline_if_needed(parts)
        if damage_context:
            resolved_context = damage_context.replace("[a/an]", "you").replace("[verb]", "are")
            if not resolved_context.endswith("."):
                resolved_context += "."
            parts.append(build_part(resolved_context))
        elif total_damage > 0:
            parts.extend([
                build_part("You are hit by "),
                build_part(skill_name),
                build_part("."),
            ])
        else:
            parts.extend([
                build_part("You avoid "),
                build_part(skill_name),
                build_part("."),
            ])

        _set_entity_skill_cooldown(entity, skill)
        _apply_entity_skill_lag(entity, skill)
        return True

    return False


def cast_spell(session: ClientSession, spell: dict, target_name: str | None = None) -> tuple[dict, bool]:
    from display import build_part, display_command_result, display_error

    spell_name = str(spell.get("name", "Spell")).strip() or "Spell"
    mana_cost = max(0, int(spell.get("mana_cost", 0)))
    spell_type = str(spell.get("spell_type", "damage")).strip().lower() or "damage"
    cast_type = str(spell.get("cast_type", "target")).strip().lower() or "target"

    damage_context = str(spell.get("damage_context", "")).strip()
    support_effect = str(spell.get("support_effect", "")).strip().lower()
    support_amount = max(0, int(spell.get("support_amount", 0)))
    duration_hours = max(0, int(spell.get("duration_hours", 0)))
    duration_rounds = max(0, int(spell.get("duration_rounds", 0)))
    support_mode = str(spell.get("support_mode", "timed")).strip().lower() or "timed"
    support_context = str(spell.get("support_context", "")).strip()
    observer_action = str(spell.get("observer_action", "")).strip()
    observer_context = str(spell.get("observer_context", "")).strip()
    spell_id = str(spell.get("spell_id", spell_name)).strip() or spell_name
    actor_name = session.authenticated_character_name or "Someone"

    status = session.status
    if status.mana < mana_cost:
        return display_error(
            f"Not enough mana for {spell_name}. Need {mana_cost}M, have {status.mana}M.",
            session,
        ), False

    if cast_type not in {"self", "target", "aoe"}:
        return display_error(f"Spell '{spell_name}' has unsupported cast_type '{cast_type}'.", session), False

    if spell_type == "support":
        if cast_type != "self":
            return display_error(f"Support spell '{spell_name}' must be cast_type 'self'.", session), False
        if support_effect not in {"heal", "vigor", "mana"}:
            return display_error(
                f"Spell '{spell_name}' has unsupported support_effect '{support_effect}'.",
                session,
            ), False
        if support_mode not in {"timed", "instant", "battle_rounds"}:
            return display_error(
                f"Spell '{spell_name}' has unsupported support_mode '{support_mode}'.",
                session,
            ), False
        if support_mode == "timed" and duration_hours <= 0:
            return display_error(
                f"Spell '{spell_name}' must have duration_hours > 0.",
                session,
            ), False
        if support_mode == "battle_rounds" and duration_rounds <= 0:
            return display_error(
                f"Spell '{spell_name}' must have duration_rounds > 0.",
                session,
            ), False
        if not support_context:
            return display_error(
                f"Spell '{spell_name}' must define support_context.",
                session,
            ), False

        status.mana -= mana_cost

        if support_mode == "instant":
            parts = [
                build_part("You cast "),
                build_part(spell_name),
                build_part("."),
            ]

            if support_effect == "heal":
                status.hit_points = min(PLAYER_REFERENCE_MAX_HP, status.hit_points + support_amount)
            elif support_effect == "vigor":
                status.vigor = min(PLAYER_REFERENCE_MAX_VIGOR, status.vigor + support_amount)
            else:
                status.mana = min(PLAYER_REFERENCE_MAX_MANA, status.mana + support_amount)
            parts.extend([
                build_part("\n"),
                build_part(support_context),
            ])
            observer_lines = [
                _render_observer_template(observer_action, actor_name) if observer_action else f"{actor_name} casts {spell_name}.",
            ]
            support_observer_context = observer_context or _observer_context_from_player_context(support_context)
            if support_observer_context:
                observer_lines.append(_render_observer_template(support_observer_context, actor_name))

            result = display_command_result(session, parts)
            return _attach_room_broadcast_parts(result, observer_lines), True

        refreshed = False
        for active_effect in session.active_support_effects:
            if active_effect.spell_id != spell_id:
                continue
            active_effect.support_mode = support_mode
            active_effect.support_effect = support_effect
            active_effect.support_amount = support_amount
            active_effect.remaining_hours = duration_hours
            active_effect.remaining_rounds = duration_rounds
            refreshed = True
            break

        if not refreshed:
            session.active_support_effects.append(ActiveSupportEffectState(
                spell_id=spell_id,
                spell_name=spell_name,
                support_mode=support_mode,
                support_effect=support_effect,
                support_amount=support_amount,
                remaining_hours=duration_hours,
                remaining_rounds=duration_rounds,
            ))

        parts = [
            build_part("You cast "),
            build_part(spell_name),
            build_part("."),
            build_part("\n"),
            build_part(support_context),
        ]
        observer_lines = [
            _render_observer_template(observer_action, actor_name) if observer_action else f"{actor_name} casts {spell_name}.",
        ]
        support_observer_context = observer_context or _observer_context_from_player_context(support_context)
        if support_observer_context:
            observer_lines.append(_render_observer_template(support_observer_context, actor_name))

        result = display_command_result(session, parts)
        return _attach_room_broadcast_parts(result, observer_lines), True

    if spell_type != "damage":
        return display_error(f"Spell '{spell_name}' has unsupported spell_type '{spell_type}'.", session), False

    clear_combat_if_invalid(session)

    damage_targets: list[EntityState] = []
    if cast_type == "target":
        entity: EntityState | None = None
        if target_name:
            entity, resolve_error = resolve_room_entity_selector(
                session,
                session.player.current_room_id,
                target_name,
                living_only=True,
            )
            if entity is None:
                return display_error(resolve_error or f"No target named '{target_name}' is here.", session), False
        else:
            entity = get_engaged_entity(session)
            if entity is None:
                return display_error("Target spell requires a target: cast 'spell' <target>", session), False
        damage_targets.append(entity)
    elif cast_type == "aoe":
        for entity in list_room_entities(session, session.player.current_room_id):
            if not entity.is_alive:
                continue
            if entity.is_ally:
                continue
            damage_targets.append(entity)

        if not damage_targets:
            return display_error("No valid hostile targets in the room.", session), False
    else:
        return display_error(f"Damage spell '{spell_name}' cannot be cast as '{cast_type}'.", session), False

    status.mana -= mana_cost

    total_damage = roll_spell_damage(spell)
    destroyed_entity_names: list[str] = []

    parts = [
        build_part("You cast "),
        build_part(spell_name),
        build_part("."),
    ]

    for index, entity in enumerate(damage_targets):
        parts.append(build_part("\n"))

        named_target = with_article(entity.name, capitalize=True)
        resolved_context = damage_context.replace("[a/an]", named_target)
        if resolved_context and not resolved_context.endswith("."):
            resolved_context += "."

        if total_damage > 0:
            entity.hit_points = max(0, entity.hit_points - total_damage)
            if resolved_context:
                parts.append(build_part(resolved_context))
            else:
                parts.extend([
                    build_part(named_target),
                    build_part(" is struck by "),
                    build_part(spell_name),
                    build_part("."),
                ])
        else:
            parts.extend([
                build_part(named_target),
                build_part(" resists "),
                build_part(spell_name),
                build_part("."),
            ])

        if entity.hit_points <= 0:
            entity.is_alive = False
            spawn_corpse_for_entity(session, entity)
            destroyed_entity_names.append(entity.name)
            parts.extend([
                build_part("\n"),
                build_part(with_article(entity.name, capitalize=True)),
                build_part(" is destroyed."),
            ])

            if entity.entity_id in session.combat.engaged_entity_ids:
                session.combat.engaged_entity_ids.discard(entity.entity_id)
                next_target = _engage_next_targeting_entity(session, entity.entity_id)
                if next_target is not None:
                    parts.extend([
                        build_part("\n"),
                        build_part("You turn to "),
                        build_part(with_article(next_target.name)),
                        build_part("."),
                    ])

    target_label = with_article(damage_targets[0].name, capitalize=True) if damage_targets else None
    observer_lines = [
        _render_observer_template(observer_action, actor_name) if observer_action else f"{actor_name} casts {spell_name}.",
    ]
    damage_observer_context = observer_context or _observer_context_from_player_context(damage_context, target_label)
    if damage_observer_context:
        observer_lines.append(_render_observer_template(damage_observer_context, actor_name))
    for destroyed_name in destroyed_entity_names:
        observer_lines.append(f"{with_article(destroyed_name, capitalize=True)} is destroyed.")

    result = display_command_result(session, parts)
    return _attach_room_broadcast_parts(result, observer_lines), True


def initialize_session_entities(session: ClientSession) -> None:
    if session.entities:
        return

    next_spawn_sequence = max((entity.spawn_sequence for entity in session.entities.values()), default=0)

    for room in WORLD.rooms.values():
        for npc_spawn in room.npcs:
            npc_id = str(npc_spawn.get("npc_id", "")).strip()
            if not npc_id:
                continue

            template = get_npc_template_by_id(npc_id)
            if template is None:
                continue

            spawn_count = max(1, int(npc_spawn.get("count", 1)))
            for _ in range(spawn_count):
                next_spawn_sequence += 1
                session.entity_spawn_counter = max(session.entity_spawn_counter, next_spawn_sequence)

                loot_items: list[LootItemState] = []
                for loot_template in template.get("loot_items", []):
                    loot_items.append(LootItemState(
                        item_id=f"loot-{uuid.uuid4().hex[:8]}",
                        name=str(loot_template.get("name", "Loot")).strip() or "Loot",
                        description=str(loot_template.get("description", "")),
                        keywords=list(loot_template.get("keywords", [])),
                    ))

                entity = EntityState(
                    entity_id=f"npc-{uuid.uuid4().hex[:8]}",
                    name=str(template.get("name", "NPC")).strip() or "NPC",
                    room_id=room.room_id,
                    hit_points=int(template.get("hit_points", 1)),
                    max_hit_points=int(template.get("max_hit_points", template.get("hit_points", 1))),
                    power_level=max(0, int(template.get("power_leveL", 1))),
                    attacks_per_round=max(1, int(template.get("attacks_per_round", 1))),
                    hit_roll_modifier=int(template.get("hit_roll_modifier", 0)),
                    armor_class=int(template.get("armor_class", 10)),
                    off_hand_attacks_per_round=max(0, int(template.get("off_hand_attacks_per_round", 0))),
                    off_hand_hit_roll_modifier=int(template.get("off_hand_hit_roll_modifier", 0)),
                    coin_reward=max(0, int(template.get("coin_reward", 0))),
                    loot_items=loot_items,
                    spawn_sequence=session.entity_spawn_counter,
                    is_aggro=bool(template.get("is_aggro", False)),
                    is_ally=bool(template.get("is_ally", False)),
                    pronoun_possessive=str(template.get("pronoun_possessive", "its")).strip().lower() or "its",
                    main_hand_weapon_template_id=str(template.get("main_hand_weapon_template_id", "")).strip(),
                    off_hand_weapon_template_id=str(template.get("off_hand_weapon_template_id", "")).strip(),
                    skill_use_chance=max(0.0, min(1.0, float(template.get("skill_use_chance", 0.35)))),
                    skill_ids=[str(skill_id).strip() for skill_id in template.get("skill_ids", []) if str(skill_id).strip()],
                )
                session.entities[entity.entity_id] = entity


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


def spawn_dummy(session: ClientSession) -> dict:
    from display import build_part, display_command_result

    room_id = session.player.current_room_id
    existing_names = {entity.name for entity in list_room_entities(session, room_id)}

    dummy_number = 1
    dummy_name = "Training Dummy"
    while dummy_name in existing_names:
        dummy_number += 1
        dummy_name = f"Training Dummy {dummy_number}"

    entity_id = f"dummy-{uuid.uuid4().hex[:8]}"
    next_spawn_sequence = max((entity.spawn_sequence for entity in session.entities.values()), default=0) + 1
    session.entity_spawn_counter = max(session.entity_spawn_counter, next_spawn_sequence)
    entity = EntityState(
        entity_id=entity_id,
        name=dummy_name,
        room_id=room_id,
        hit_points=40,
        max_hit_points=40,
        power_level=6,
        attacks_per_round=1,
        coin_reward=12,
        spawn_sequence=next_spawn_sequence,
    )
    session.entities[entity_id] = entity

    return display_command_result(session, [
        build_part("Spawned ", "bright_white"),
        build_part(entity.name, bold=True),
        build_part(" in this room.", "bright_white"),
    ])


def begin_attack(session: ClientSession, target_name: str) -> dict | list[dict]:
    from display import build_part, display_command_result, display_error

    clear_combat_if_invalid(session)
    entity, resolve_error = resolve_room_entity_selector(
        session,
        session.player.current_room_id,
        target_name,
        living_only=True,
    )

    if entity is None:
        return display_error(resolve_error or f"No target named '{target_name}' is here.", session)

    started = start_combat(session, entity.entity_id, OPENING_ATTACKER_PLAYER)
    if not started:
        return display_error(f"{entity.name} is already engaged with another target.", session)

    return display_command_result(session, [
        build_part("You engage ", "bright_white"),
        build_part(with_article(entity.name), "bright_yellow", True),
        build_part(".", "bright_white"),
    ])


def disengage(session: ClientSession) -> dict | list[dict]:
    from display import build_part, display_command_result, display_error

    clear_combat_if_invalid(session)

    entity = get_engaged_entity(session)
    if entity is None:
        return display_error("You are not engaged with anything.", session)

    end_combat(session)

    target_name = entity.name if entity is not None else "your target"
    return display_command_result(session, [
        build_part("You disengage from ", "bright_white"),
        build_part(target_name, bold=True),
        build_part(".", "bright_white"),
    ])


def _apply_player_attacks(session: ClientSession, entity: EntityState, parts: list[dict], allow_off_hand: bool) -> None:
    attack_sequence = _build_player_attack_sequence(session, allow_off_hand)

    for weapon in attack_sequence:
        if not entity.is_alive:
            break

        append_newline_if_needed(parts)

        hit_modifier = get_player_hit_modifier(weapon)
        if not roll_hit(hit_modifier, entity.armor_class):
            miss_verb = resolve_weapon_verb(weapon.weapon_type) if weapon is not None else "hit"
            parts.extend(build_player_attack_parts(
                entity_name=entity.name,
                attack_verb=miss_verb,
                damage=0,
                target_max_hp=entity.max_hit_points,
            ))
            continue

        rolled_damage, weapon_name, attack_verb = roll_player_damage(session.player_combat, weapon)
        entity.hit_points = max(0, entity.hit_points - rolled_damage)
        parts.extend(build_player_attack_parts(
            entity_name=entity.name,
            attack_verb=attack_verb,
            damage=rolled_damage,
            target_max_hp=entity.max_hit_points,
        ))

        if entity.hit_points <= 0:
            entity.is_alive = False
            break


def _apply_entity_attacks(session: ClientSession, attacker: EntityState, parts: list[dict], allow_off_hand: bool) -> None:
    status = session.status
    player_armor_class = get_player_armor_class(session)

    def _resolve_npc_weapon_template(template_id: str) -> dict | None:
        normalized_template_id = template_id.strip()
        if not normalized_template_id:
            return None
        template = get_equipment_template_by_id(normalized_template_id)
        if template is None:
            return None
        if str(template.get("slot", "")).strip().lower() != "weapon":
            return None
        return template

    entity = attacker
    if not entity.is_alive:
        return

    # Skills are additive and do not consume the entity's melee turn.
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

    if allow_off_hand:
        off_hand_swings = max(0, entity.off_hand_attacks_per_round)
        for _ in range(off_hand_swings):
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

    if entity.hit_points <= 0:
        entity.is_alive = False
        spawn_corpse_for_entity(session, entity)

        append_newline_if_needed(parts)
        parts.extend([
            build_part(with_article(entity.name, capitalize=True)),
            build_part(" is destroyed.", "bright_white"),
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

        return display_combat_round_result(session, parts)

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

    if status.hit_points <= 0:
        end_combat(session)

        append_newline_if_needed(parts)
        parts.extend([
            build_part("You collapse. Combat ends.", "bright_red", True),
        ])

        result = display_combat_round_result(session, parts)
        payload = result.get("payload") if isinstance(result, dict) else None
        if isinstance(payload, dict):
            actor_name = session.authenticated_character_name or "Someone"
            payload["room_broadcast_parts"] = [
                build_part(f"{actor_name} collapses. Combat ends.", "bright_red", True),
            ]

        return result

    _schedule_next_combat_round(session)
    return display_combat_round_result(session, parts)