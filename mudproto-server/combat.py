import asyncio
import random
import re
import uuid

from grammar import with_article
from experience import award_experience
from player_resources import get_player_resource_caps, roll_level_resource_gains
from assets import get_gear_template_by_id, get_npc_template_by_id, get_skill_by_id, get_spell_by_id
from battle_round_ticks import process_battle_round_support_effects
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
    roll_skill_damage,
    roll_spell_damage,
)
from equipment import get_equipped_main_hand, get_equipped_off_hand, get_player_armor_class
from inventory import build_equippable_item_from_template
from models import ActiveSupportEffectState, ClientSession, CorpseState, EntityState, ItemState
from sessions import (
    active_character_sessions,
    connected_clients,
    shared_world_corpses,
    shared_world_entities,
    shared_world_room_coin_piles,
    shared_world_room_ground_items,
)
from death import build_player_death_broadcast_parts, build_player_death_mourn_parts, build_player_death_parts, handle_player_death
from settings import (
    COMBAT_ROUND_INTERVAL_SECONDS,
)
from world import WORLD


OPENING_ATTACKER_PLAYER = "player"
OPENING_ATTACKER_ENTITY = "entity"


def _append_experience_gain_parts(session: ClientSession, entity: EntityState, parts: list[dict], build_part_fn) -> None:
    experience_reward = max(0, int(getattr(entity, "experience_reward", 0)))
    gained, old_level, new_level, _ = award_experience(session, experience_reward)
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


def _resolve_secondary_restore_fields(ability: dict) -> tuple[str, float, str, str]:
    restore_effect = str(ability.get("restore_effect", "")).strip().lower()
    restore_ratio = float(ability.get("restore_ratio", ability.get("life_steal_ratio", 0.0)))
    if not restore_effect and restore_ratio > 0.0 and float(ability.get("life_steal_ratio", 0.0)) > 0.0:
        restore_effect = "heal"

    restore_context = str(ability.get("restore_context", ability.get("life_steal_context", ""))).strip()
    observer_restore_context = str(
        ability.get("observer_restore_context", ability.get("observer_life_steal_context", ""))
    ).strip()
    return restore_effect, max(0.0, min(1.0, restore_ratio)), restore_context, observer_restore_context


def _player_restore_fallback(effect: str) -> str:
    if effect == "mana":
        return "Arcane current rushes back into your spirit."
    if effect == "vigor":
        return "Battle fervor surges back through your limbs."
    return "Stolen vitality surges back through your veins."


def _observer_restore_fallback(effect: str) -> str:
    if effect == "mana":
        return "Arcane current recoils into [actor_name], renewing [actor_object]."
    if effect == "vigor":
        return "Battle fervor surges back through [actor_possessive] limbs."
    return "Vital force recoils into [actor_name], renewing [actor_object]."


def _apply_player_secondary_restore(session: ClientSession, effect: str, amount: int) -> int:
    if amount <= 0:
        return 0

    caps = get_player_resource_caps(session)

    if effect == "mana":
        before = session.status.mana
        session.status.mana = min(caps["mana"], session.status.mana + amount)
        return session.status.mana - before
    if effect == "vigor":
        before = session.status.vigor
        session.status.vigor = min(caps["vigor"], session.status.vigor + amount)
        return session.status.vigor - before

    before = session.status.hit_points
    session.status.hit_points = min(caps["hit_points"], session.status.hit_points + amount)
    return session.status.hit_points - before


def _apply_entity_secondary_restore(entity: EntityState, effect: str, amount: int) -> int:
    if amount <= 0:
        return 0

    if effect == "mana":
        before = entity.mana
        entity.mana = min(entity.max_mana, entity.mana + amount)
        return entity.mana - before
    if effect == "vigor":
        before = entity.vigor
        entity.vigor = min(entity.max_vigor, entity.vigor + amount)
        return entity.vigor - before

    before = entity.hit_points
    entity.hit_points = min(entity.max_hit_points, entity.hit_points + amount)
    return entity.hit_points - before


def _resolve_player_support_scaling_bonus(session: ClientSession, spell: dict, support_effect: str) -> int:
    scaling_attribute_id = str(spell.get("support_scaling_attribute_id", "")).strip().lower()
    if not scaling_attribute_id and support_effect == "heal":
        scaling_attribute_id = "wis"
    level_scaling_multiplier = max(0.0, float(spell.get("level_scaling_multiplier", 1.0)))

    scaling_bonus = 0
    if scaling_attribute_id:
        scaling_multiplier = max(0.0, float(spell.get("support_scaling_multiplier", 1.0)))
        if scaling_multiplier > 0.0:
            attribute_score = int(session.player.attributes.get(scaling_attribute_id, 0))
            attribute_modifier = (attribute_score - 10) // 2
            scaling_bonus += int(attribute_modifier * scaling_multiplier)

    if level_scaling_multiplier > 0.0:
        scaling_bonus += int(max(1, int(session.player.level)) * level_scaling_multiplier)

    return scaling_bonus


def _resolve_player_damage_scaling_bonus(session: ClientSession, spell: dict) -> int:
    scaling_attribute_id = str(spell.get("damage_scaling_attribute_id", "int")).strip().lower() or "int"
    scaling_multiplier = max(0.0, float(spell.get("damage_scaling_multiplier", 1.0)))
    level_scaling_multiplier = max(0.0, float(spell.get("level_scaling_multiplier", 1.0)))

    scaling_bonus = 0
    if scaling_multiplier > 0.0:
        attribute_score = int(session.player.attributes.get(scaling_attribute_id, 0))
        attribute_modifier = (attribute_score - 10) // 2
        scaling_bonus += int(attribute_modifier * scaling_multiplier)

    if level_scaling_multiplier > 0.0:
        scaling_bonus += int(max(1, int(session.player.level)) * level_scaling_multiplier)

    return scaling_bonus


def _roll_player_support_amount(
    session: ClientSession,
    spell: dict,
    support_effect: str,
) -> tuple[int, int, int, int, int]:
    base_amount = max(0, int(spell.get("support_amount", 0)))
    dice_count = max(0, int(spell.get("support_dice_count", 0)))
    dice_sides = max(0, int(spell.get("support_dice_sides", 0)))
    roll_modifier = int(spell.get("support_roll_modifier", 0))
    scaling_bonus = _resolve_player_support_scaling_bonus(session, spell, support_effect)

    rolled_amount = base_amount + roll_modifier + scaling_bonus
    if dice_count > 0 and dice_sides > 0:
        rolled_amount += sum(random.randint(1, dice_sides) for _ in range(dice_count))

    return max(0, rolled_amount), dice_count, dice_sides, roll_modifier, scaling_bonus


def _resolve_entity_support_scaling_bonus(entity: EntityState, spell: dict, support_effect: str) -> int:
    scaling_attribute_id = str(spell.get("support_scaling_attribute_id", "")).strip().lower()
    if not scaling_attribute_id and support_effect == "heal":
        scaling_attribute_id = "power_level"
    if scaling_attribute_id != "power_level":
        return 0

    scaling_multiplier = max(0.0, float(spell.get("support_scaling_multiplier", 1.0)))
    if scaling_multiplier <= 0.0:
        return 0

    return int(max(0, entity.power_level) * scaling_multiplier)


def _resolve_entity_damage_scaling_bonus(entity: EntityState, spell: dict) -> int:
    scaling_multiplier = max(0.0, float(spell.get("damage_scaling_multiplier", 1.0)))
    if scaling_multiplier <= 0.0:
        return 0

    return int(max(0, entity.power_level) * scaling_multiplier)


def _roll_entity_support_amount(
    entity: EntityState,
    spell: dict,
    support_effect: str,
) -> tuple[int, int, int, int, int]:
    base_amount = max(0, int(spell.get("support_amount", 0)))
    dice_count = max(0, int(spell.get("support_dice_count", 0)))
    dice_sides = max(0, int(spell.get("support_dice_sides", 0)))
    roll_modifier = int(spell.get("support_roll_modifier", 0))
    scaling_bonus = _resolve_entity_support_scaling_bonus(entity, spell, support_effect)

    rolled_amount = base_amount + roll_modifier + scaling_bonus
    if dice_count > 0 and dice_sides > 0:
        rolled_amount += sum(random.randint(1, dice_sides) for _ in range(dice_count))

    return max(0, rolled_amount), dice_count, dice_sides, roll_modifier, scaling_bonus


def _roll_support_effect_amount(effect: ActiveSupportEffectState) -> int:
    rolled_amount = int(effect.support_amount)
    rolled_amount += int(effect.support_roll_modifier)
    rolled_amount += int(effect.support_scaling_bonus)

    dice_count = max(0, int(effect.support_dice_count))
    dice_sides = max(0, int(effect.support_dice_sides))
    if dice_count > 0 and dice_sides > 0:
        rolled_amount += sum(random.randint(1, dice_sides) for _ in range(dice_count))

    return max(0, rolled_amount)


def _process_entity_battle_round_support_effects(entity: EntityState) -> None:
    for effect in list(entity.active_support_effects):
        if effect.support_mode != "battle_rounds":
            continue

        rolled_amount = _roll_support_effect_amount(effect)
        _apply_entity_secondary_restore(entity, effect.support_effect, rolled_amount)

        effect.remaining_rounds -= 1
        if effect.remaining_rounds <= 0:
            entity.active_support_effects.remove(effect)


def process_entity_game_hour_tick(entity: EntityState) -> None:
    for effect in list(entity.active_support_effects):
        if effect.support_mode != "timed":
            continue

        rolled_amount = _roll_support_effect_amount(effect)
        _apply_entity_secondary_restore(entity, effect.support_effect, rolled_amount)

        effect.remaining_hours -= 1
        if effect.remaining_hours <= 0:
            entity.active_support_effects.remove(effect)


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


def _entity_name_keywords(name: str) -> set[str]:
    return {token for token in re.findall(r"[a-zA-Z0-9]+", name.lower()) if token}


def _corpse_keywords(corpse: CorpseState) -> set[str]:
    keywords = _entity_name_keywords(corpse.source_name)
    keywords.add("corpse")
    return keywords


def _corpse_item_keywords(item: ItemState) -> set[str]:
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


def resolve_corpse_item_selector(corpse: CorpseState, selector_text: str) -> tuple[ItemState | None, str | None]:
    normalized = selector_text.strip().lower()
    if not normalized:
        return None, "Provide an item selector."

    items = list(corpse.loot_items.values())
    if not items:
        return None, "That corpse has no lootable items."

    items.sort(key=lambda item: item.name.lower())

    if "." not in normalized:
        exact_match: ItemState | None = None
        partial_match: ItemState | None = None
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

    matches: list[ItemState] = []
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
    from display import build_part, display_command_result

    return display_command_result(session, [
        build_part("Relax. ", "bright_yellow", True),
        build_part(f"{entity.name} is peaceful.", "bright_white"),
    ])


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


def _resolve_player_skill_scale_bonus(session: ClientSession, skill: dict) -> int:
    scaling_attribute_id = str(skill.get("scaling_attribute_id", "")).strip().lower()
    scaling_multiplier = max(0.0, float(skill.get("scaling_multiplier", 0.0)))
    level_scaling_multiplier = max(0.0, float(skill.get("level_scaling_multiplier", 1.0)))

    scaling_bonus = 0
    if scaling_attribute_id and scaling_multiplier > 0.0:
        attribute_value = int(session.player.attributes.get(scaling_attribute_id, 0))
        scaling_bonus += int(attribute_value * scaling_multiplier)

    if level_scaling_multiplier > 0.0:
        scaling_bonus += int(max(1, int(session.player.level)) * level_scaling_multiplier)

    return max(0, scaling_bonus)


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


def tick_out_of_combat_cooldowns(session: ClientSession) -> None:
    """Decrement player skill cooldowns for sessions not currently in combat."""
    _decrement_cooldowns(session.combat.skill_cooldowns)


def _apply_player_skill_lag(session: ClientSession, skill: dict) -> None:
    # Lag is tracked for visual feedback but doesn't skip melee rounds.
    # Skills have lag_rounds but this doesn't prevent player melee attacks.
    pass


def _apply_entity_skill_lag(entity: EntityState, skill: dict) -> None:
    lag_rounds = max(0, int(skill.get("lag_rounds", 0)))
    if lag_rounds > 0:
        entity.skill_lag_rounds_remaining = max(entity.skill_lag_rounds_remaining, lag_rounds)


def _set_entity_spell_cooldown(entity: EntityState, spell: dict) -> None:
    cooldown_rounds = max(0, int(spell.get("cooldown_rounds", 0)))
    if cooldown_rounds > 0:
        spell_id = str(spell.get("spell_id", "")).strip()
        if spell_id:
            entity.spell_cooldowns[spell_id] = cooldown_rounds


def _apply_entity_spell_lag(entity: EntityState, spell: dict) -> None:
    lag_rounds = max(0, int(spell.get("lag_rounds", 0)))
    if lag_rounds > 0:
        entity.spell_lag_rounds_remaining = max(entity.spell_lag_rounds_remaining, lag_rounds)


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

    if get_engaged_entity(session) is None and not usable_out_of_combat:
        return display_error(f"{skill_name} can only be used while in combat.", session), False

    if skill_id and session.combat.skill_cooldowns.get(skill_id, 0) > 0:
        return display_error(
            f"{skill_name} is on cooldown for {session.combat.skill_cooldowns[skill_id]} more round(s).",
            session,
        ), False

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
    if description and skill_type != "support":
        parts.extend([
            build_part(" "),
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
        caps = get_player_resource_caps(session)

        total_support_amount = max(0, support_amount + scaling_bonus)

        if support_effect == "heal":
            session.status.hit_points = min(caps["hit_points"], session.status.hit_points + total_support_amount)
        elif support_effect == "vigor":
            session.status.vigor = min(caps["vigor"], session.status.vigor + total_support_amount)
        else:
            session.status.mana = min(caps["mana"], session.status.mana + total_support_amount)

        if support_context:
            parts.extend([
                build_part("\n"),
                build_part(support_context),
            ])

        _set_player_skill_cooldown(session, skill)
        _apply_player_skill_lag(session, skill)
        observer_lines = [
            _resolve_observer_action_line(
                actor_name,
                "uses",
                skill_name,
                cast_type,
                observer_action=observer_action,
            ),
        ]
        support_observer_context = observer_context or _observer_context_from_player_context(support_context)
        if support_observer_context:
            observer_lines.append(_render_observer_template(support_observer_context, actor_name))

        result = display_command_result(session, parts, blank_lines_before=0)
        return _attach_room_broadcast_lines(result, observer_lines), True

    clear_combat_if_invalid(session)

    damage_targets: list[EntityState] = []
    peaceful_targets_for_feedback: list[EntityState] = []
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
        if bool(getattr(entity, "is_peaceful", False)):
            peaceful_targets_for_feedback.append(entity)
        else:
            damage_targets.append(entity)
    elif cast_type == "aoe":
        for entity in list_room_entities(session, session.player.current_room_id):
            if not entity.is_alive:
                continue
            if bool(getattr(entity, "is_peaceful", False)):
                peaceful_targets_for_feedback.append(entity)
                continue
            if entity.is_ally:
                continue
            damage_targets.append(entity)
        if not damage_targets and not peaceful_targets_for_feedback:
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
    restore_effect, restore_ratio, restore_context, observer_restore_context = _resolve_secondary_restore_fields(skill)
    total_damage_dealt = 0
    destroyed_entity_names: list[str] = []

    for entity in damage_targets:
        parts.append(build_part("\n"))
        named_target = with_article(entity.name, capitalize=True)
        resolved_context = damage_context.replace("[a/an]", named_target).replace("[verb]", "is")
        if resolved_context and not resolved_context.endswith("."):
            resolved_context += "."

        if total_damage > 0:
            dealt = min(entity.hit_points, total_damage)
            entity.hit_points = max(0, entity.hit_points - total_damage)
            total_damage_dealt += max(0, dealt)
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
            _append_experience_gain_parts(session, entity, parts, build_part)
            destroyed_entity_names.append(entity.name)
            parts.extend([
                build_part("\n"),
                build_part(with_article(entity.name, capitalize=True), "bright_red", True),
                build_part(" is dead!", "bright_red", True),
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

    if not damage_targets and peaceful_targets_for_feedback:
        parts.extend([
            build_part("\n"),
            build_part(f"{peaceful_targets_for_feedback[0].name} remains untouched."),
        ])

    restored_amount = 0
    if restore_ratio > 0.0 and total_damage_dealt > 0:
        restore_amount = int(total_damage_dealt * restore_ratio)
        restored_amount = _apply_player_secondary_restore(session, restore_effect, restore_amount)
        if restored_amount > 0:
            parts.extend([
                build_part("\n"),
                build_part(restore_context or _player_restore_fallback(restore_effect)),
            ])

    _set_player_skill_cooldown(session, skill)
    _apply_player_skill_lag(session, skill)
    target_label = with_article(damage_targets[0].name, capitalize=True) if damage_targets else None
    observer_lines = [
        _resolve_observer_action_line(
            actor_name,
            "uses",
            skill_name,
            cast_type,
            target_label=target_label,
            observer_action=observer_action,
        ),
    ]
    damage_observer_context = observer_context or _observer_context_from_player_context(damage_context, target_label)
    if damage_observer_context:
        observer_lines.append(_render_observer_template(damage_observer_context, actor_name))
    if restored_amount > 0:
        observer_lines.append(_render_observer_template(
            observer_restore_context or _observer_restore_fallback(restore_effect),
            actor_name,
        ))
    for destroyed_name in destroyed_entity_names:
        observer_lines.append(f"{with_article(destroyed_name, capitalize=True)} is dead!")

    result = display_command_result(session, parts, blank_lines_before=0)
    return _attach_room_broadcast_lines(result, observer_lines), True


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
        vigor_cost = max(0, int(skill.get("vigor_cost", 0)))
        if entity.vigor < vigor_cost:
            continue
        available_skills.append(skill)

    if not available_skills:
        return False

    skill = random.choice(available_skills)
    skill_name = str(skill.get("name", "Skill")).strip() or "Skill"
    skill_type = str(skill.get("skill_type", "damage")).strip().lower() or "damage"
    cast_type = str(skill.get("cast_type", "target")).strip().lower() or "target"
    vigor_cost = max(0, int(skill.get("vigor_cost", 0)))
    scaling_bonus = _resolve_entity_skill_scale_bonus(entity, skill)
    observer_context = str(skill.get("observer_context", "")).strip()

    description = str(skill.get("description", "")).strip()
    cast_target_text = " on you!"
    if skill_type == "support" and cast_type == "self":
        cast_target_text = " on themselves!"
    elif cast_type == "aoe":
        cast_target_text = " across the room!"
    
    append_newline_if_needed(parts)
    parts.extend([
        build_part(with_article(entity.name, capitalize=True)),
        build_part(" uses "),
        build_part(skill_name),
        build_part(cast_target_text),
    ])
    if description and skill_type != "support":
        parts.extend([
            build_part(" "),
            build_part(description),
        ])

    entity.vigor = max(0, entity.vigor - vigor_cost)

    if skill_type == "support" and cast_type == "self":
        support_effect = str(skill.get("support_effect", "")).strip().lower()
        support_amount = max(0, int(skill.get("support_amount", 0)))
        support_context = str(skill.get("support_context", "")).strip()
        total_support_amount = max(0, support_amount + scaling_bonus)

        if support_effect == "heal":
            entity.hit_points = min(entity.max_hit_points, entity.hit_points + total_support_amount)
        elif support_effect == "vigor":
            entity.vigor = min(entity.max_vigor, entity.vigor + total_support_amount)
        elif support_effect == "mana":
            entity.mana = min(entity.max_mana, entity.mana + total_support_amount)
        if support_context:
            rendered_support_context = observer_context or _observer_context_from_player_context(support_context)
            append_newline_if_needed(parts)
            parts.append(build_part(_render_observer_template(
                rendered_support_context,
                with_article(entity.name, capitalize=True),
            )))

        _set_entity_skill_cooldown(entity, skill)
        _apply_entity_skill_lag(entity, skill)
        return True

    if skill_type == "damage" and cast_type in {"target", "aoe"}:
        total_damage = roll_skill_damage(skill) + scaling_bonus
        damage_context = str(skill.get("damage_context", "")).strip()
        restore_effect, restore_ratio, _, observer_restore_context = _resolve_secondary_restore_fields(skill)
        damage_dealt = 0

        if total_damage > 0:
            damage_dealt = min(session.status.hit_points, total_damage)
            session.status.hit_points = max(0, session.status.hit_points - total_damage)

        restored_amount = 0
        if restore_ratio > 0.0 and damage_dealt > 0:
            restore_amount = int(damage_dealt * restore_ratio)
            restored_amount = _apply_entity_secondary_restore(entity, restore_effect, restore_amount)

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

        if restored_amount > 0:
            append_newline_if_needed(parts)
            rendered_restore_context = _render_observer_template(
                observer_restore_context or _observer_restore_fallback(restore_effect),
                with_article(entity.name, capitalize=True),
            )
            parts.append(build_part(rendered_restore_context))

        _set_entity_skill_cooldown(entity, skill)
        _apply_entity_skill_lag(entity, skill)
        return True

    return False


def _entity_try_cast_spell(session: ClientSession, entity: EntityState, parts: list[dict]) -> bool:
    from display import build_part

    if not entity.spell_ids:
        return False

    chance = max(0.0, min(1.0, float(entity.spell_use_chance)))
    if random.random() >= chance:
        return False

    available_spells: list[dict] = []
    for spell_id in entity.spell_ids:
        spell = get_spell_by_id(spell_id)
        if spell is None:
            continue
        normalized_spell_id = str(spell.get("spell_id", "")).strip()
        if normalized_spell_id and entity.spell_cooldowns.get(normalized_spell_id, 0) > 0:
            continue

        mana_cost = max(0, int(spell.get("mana_cost", 0)))
        if entity.mana < mana_cost:
            continue

        available_spells.append(spell)

    if not available_spells:
        return False

    spell = random.choice(available_spells)
    spell_name = str(spell.get("name", "Spell")).strip() or "Spell"
    spell_type = str(spell.get("spell_type", "damage")).strip().lower() or "damage"
    cast_type = str(spell.get("cast_type", "target")).strip().lower() or "target"
    mana_cost = max(0, int(spell.get("mana_cost", 0)))
    cast_target_text = " at you!"
    if spell_type == "support" and cast_type == "self":
        cast_target_text = " on themselves!"
    elif cast_type == "aoe":
        cast_target_text = " across the room!"

    append_newline_if_needed(parts)
    parts.extend([
        build_part(with_article(entity.name, capitalize=True)),
        build_part(" casts "),
        build_part(spell_name),
        build_part(cast_target_text),
    ])

    entity.mana = max(0, entity.mana - mana_cost)

    if spell_type == "support" and cast_type == "self":
        support_effect = str(spell.get("support_effect", "")).strip().lower()
        support_amount = max(0, int(spell.get("support_amount", 0)))
        support_dice_count = max(0, int(spell.get("support_dice_count", 0)))
        support_mode = str(spell.get("support_mode", "timed")).strip().lower() or "timed"
        duration_hours = max(0, int(spell.get("duration_hours", 0)))
        duration_rounds = max(0, int(spell.get("duration_rounds", 0)))
        support_context = str(spell.get("support_context", "")).strip()

        if support_amount <= 0 and support_dice_count <= 0:
            return False

        rolled_support_amount, dice_count, dice_sides, roll_modifier, scaling_bonus = _roll_entity_support_amount(
            entity,
            spell,
            support_effect,
        )

        if support_mode == "instant":
            if support_effect == "heal":
                entity.hit_points = min(entity.max_hit_points, entity.hit_points + rolled_support_amount)
            elif support_effect == "vigor":
                entity.vigor = min(entity.max_vigor, entity.vigor + rolled_support_amount)
            elif support_effect == "mana":
                entity.mana = min(entity.max_mana, entity.mana + rolled_support_amount)
        elif support_mode in {"timed", "battle_rounds"}:
            spell_id = str(spell.get("spell_id", spell_name)).strip() or spell_name
            refreshed = False
            for active_effect in entity.active_support_effects:
                if active_effect.spell_id != spell_id:
                    continue
                active_effect.support_mode = support_mode
                active_effect.support_effect = support_effect
                active_effect.support_amount = support_amount
                active_effect.support_dice_count = dice_count
                active_effect.support_dice_sides = dice_sides
                active_effect.support_roll_modifier = roll_modifier
                active_effect.support_scaling_bonus = scaling_bonus
                active_effect.remaining_hours = duration_hours
                active_effect.remaining_rounds = duration_rounds
                refreshed = True
                break

            if not refreshed:
                entity.active_support_effects.append(ActiveSupportEffectState(
                    spell_id=spell_id,
                    spell_name=spell_name,
                    support_mode=support_mode,
                    support_effect=support_effect,
                    support_amount=support_amount,
                    support_dice_count=dice_count,
                    support_dice_sides=dice_sides,
                    support_roll_modifier=roll_modifier,
                    support_scaling_bonus=scaling_bonus,
                    remaining_hours=duration_hours,
                    remaining_rounds=duration_rounds,
                ))

        if support_context:
            append_newline_if_needed(parts)
            parts.append(build_part(support_context))

        _set_entity_spell_cooldown(entity, spell)
        _apply_entity_spell_lag(entity, spell)
        return True

    if spell_type == "damage" and cast_type in {"target", "aoe"}:
        spell_damage = roll_spell_damage(spell, _resolve_entity_damage_scaling_bonus(entity, spell))
        damage_context = str(spell.get("damage_context", "")).strip()
        restore_effect, restore_ratio, _, observer_restore_context = _resolve_secondary_restore_fields(spell)
        damage_dealt = 0

        if spell_damage > 0:
            damage_dealt = min(session.status.hit_points, spell_damage)
            session.status.hit_points = max(0, session.status.hit_points - spell_damage)

        restored_amount = 0
        if restore_ratio > 0.0 and damage_dealt > 0:
            restore_amount = int(damage_dealt * restore_ratio)
            restored_amount = _apply_entity_secondary_restore(entity, restore_effect, restore_amount)

        append_newline_if_needed(parts)
        if damage_context:
            resolved_context = damage_context.replace("[a/an]", "you").replace("[verb]", "are")
            if not resolved_context.endswith("."):
                resolved_context += "."
            parts.append(build_part(resolved_context))
        elif spell_damage > 0:
            parts.extend([
                build_part("You are struck by "),
                build_part(spell_name),
                build_part("."),
            ])
        else:
            parts.extend([
                build_part("You resist "),
                build_part(spell_name),
                build_part("."),
            ])

        if restored_amount > 0:
            append_newline_if_needed(parts)
            rendered_restore_context = _render_observer_template(
                observer_restore_context or _observer_restore_fallback(restore_effect),
                with_article(entity.name, capitalize=True),
            )
            parts.append(build_part(rendered_restore_context))

        _set_entity_spell_cooldown(entity, spell)
        _apply_entity_spell_lag(entity, spell)
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
    support_dice_count = max(0, int(spell.get("support_dice_count", 0)))
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
        if support_amount <= 0 and support_dice_count <= 0:
            return display_error(
                f"Spell '{spell_name}' must define support_amount and/or support_dice_count.",
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

            rolled_support_amount, _, _, _, _ = _roll_player_support_amount(session, spell, support_effect)
            caps = get_player_resource_caps(session)
            if support_effect == "heal":
                status.hit_points = min(caps["hit_points"], status.hit_points + rolled_support_amount)
            elif support_effect == "vigor":
                status.vigor = min(caps["vigor"], status.vigor + rolled_support_amount)
            else:
                status.mana = min(caps["mana"], status.mana + rolled_support_amount)
            parts.extend([
                build_part("\n"),
                build_part(support_context),
            ])
            observer_lines = [
                _resolve_observer_action_line(
                    actor_name,
                    "casts",
                    spell_name,
                    cast_type,
                    observer_action=observer_action,
                ),
            ]
            support_observer_context = observer_context or _observer_context_from_player_context(support_context)
            if support_observer_context:
                observer_lines.append(_render_observer_template(support_observer_context, actor_name))

            result = display_command_result(session, parts, blank_lines_before=0)
            return _attach_room_broadcast_lines(result, observer_lines), True

        _, dice_count, dice_sides, roll_modifier, scaling_bonus = _roll_player_support_amount(
            session,
            spell,
            support_effect,
        )

        refreshed = False
        for active_effect in session.active_support_effects:
            if active_effect.spell_id != spell_id:
                continue
            active_effect.support_mode = support_mode
            active_effect.support_effect = support_effect
            active_effect.support_amount = support_amount
            active_effect.support_dice_count = dice_count
            active_effect.support_dice_sides = dice_sides
            active_effect.support_roll_modifier = roll_modifier
            active_effect.support_scaling_bonus = scaling_bonus
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
                support_dice_count=dice_count,
                support_dice_sides=dice_sides,
                support_roll_modifier=roll_modifier,
                support_scaling_bonus=scaling_bonus,
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
            _resolve_observer_action_line(
                actor_name,
                "casts",
                spell_name,
                cast_type,
                observer_action=observer_action,
            ),
        ]
        support_observer_context = observer_context or _observer_context_from_player_context(support_context)
        if support_observer_context:
            observer_lines.append(_render_observer_template(support_observer_context, actor_name))

        result = display_command_result(session, parts, blank_lines_before=0)
        return _attach_room_broadcast_lines(result, observer_lines), True

    if spell_type != "damage":
        return display_error(f"Spell '{spell_name}' has unsupported spell_type '{spell_type}'.", session), False

    clear_combat_if_invalid(session)

    damage_targets: list[EntityState] = []
    peaceful_targets_for_feedback: list[EntityState] = []
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
        if bool(getattr(entity, "is_peaceful", False)):
            peaceful_targets_for_feedback.append(entity)
        else:
            damage_targets.append(entity)
    elif cast_type == "aoe":
        for entity in list_room_entities(session, session.player.current_room_id):
            if not entity.is_alive:
                continue
            if bool(getattr(entity, "is_peaceful", False)):
                peaceful_targets_for_feedback.append(entity)
                continue
            if entity.is_ally:
                continue
            damage_targets.append(entity)

        if not damage_targets and not peaceful_targets_for_feedback:
            return display_error("No valid hostile targets in the room.", session), False
    else:
        return display_error(f"Damage spell '{spell_name}' cannot be cast as '{cast_type}'.", session), False

    status.mana -= mana_cost

    total_damage = roll_spell_damage(spell, _resolve_player_damage_scaling_bonus(session, spell))
    restore_effect, restore_ratio, restore_context, observer_restore_context = _resolve_secondary_restore_fields(spell)
    total_damage_dealt = 0
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
            dealt = min(entity.hit_points, total_damage)
            entity.hit_points = max(0, entity.hit_points - total_damage)
            total_damage_dealt += max(0, dealt)
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
            _append_experience_gain_parts(session, entity, parts, build_part)
            destroyed_entity_names.append(entity.name)
            parts.extend([
                build_part("\n"),
                build_part(with_article(entity.name, capitalize=True), "bright_red", True),
                build_part(" is dead!", "bright_red", True),
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

    if not damage_targets and peaceful_targets_for_feedback:
        parts.extend([
            build_part("\n"),
            build_part(f"{peaceful_targets_for_feedback[0].name} remains untouched."),
        ])

    restored_amount = 0
    if restore_ratio > 0.0 and total_damage_dealt > 0:
        restore_amount = int(total_damage_dealt * restore_ratio)
        restored_amount = _apply_player_secondary_restore(session, restore_effect, restore_amount)
        if restored_amount > 0:
            parts.extend([
                build_part("\n"),
                build_part(restore_context or _player_restore_fallback(restore_effect)),
            ])

    target_label = with_article(damage_targets[0].name, capitalize=True) if damage_targets else None
    observer_lines = [
        _resolve_observer_action_line(
            actor_name,
            "casts",
            spell_name,
            cast_type,
            target_label=target_label,
            observer_action=observer_action,
        ),
    ]
    damage_observer_context = observer_context or _observer_context_from_player_context(damage_context, target_label)
    if damage_observer_context:
        observer_lines.append(_render_observer_template(damage_observer_context, actor_name))
    if restored_amount > 0:
        observer_lines.append(_render_observer_template(
            observer_restore_context or _observer_restore_fallback(restore_effect),
            actor_name,
        ))
    for destroyed_name in destroyed_entity_names:
        observer_lines.append(f"{with_article(destroyed_name, capitalize=True)} is dead!")

    result = display_command_result(session, parts, blank_lines_before=0)
    return _attach_room_broadcast_lines(result, observer_lines), True


def _build_loot_items_from_template(template: dict) -> list[ItemState]:
    loot_items: list[ItemState] = []
    for loot_template in template.get("loot_items", []):
        loot_items.append(ItemState(
            item_id=f"loot-{uuid.uuid4().hex[:8]}",
            name=str(loot_template.get("name", "Loot")).strip() or "Loot",
            template_id=str(loot_template.get("template_id", "")).strip(),
            description=str(loot_template.get("description", "")),
            keywords=list(loot_template.get("keywords", [])),
        ))
    return loot_items


def _build_entity_from_template(template: dict, room_id: str, spawn_sequence: int) -> EntityState:
    entity = EntityState(
        f"npc-{uuid.uuid4().hex[:8]}",
        str(template.get("name", "NPC")).strip() or "NPC",
        room_id,
        int(template.get("hit_points", 1)),
        int(template.get("max_hit_points", template.get("hit_points", 1))),
    )
    entity.npc_id = str(template.get("npc_id", "")).strip()
    entity.power_level = max(0, int(template.get("power_level", 1)))
    entity.attacks_per_round = max(1, int(template.get("attacks_per_round", 1)))
    entity.hit_roll_modifier = int(template.get("hit_roll_modifier", 0))
    entity.armor_class = int(template.get("armor_class", 10))
    entity.off_hand_attacks_per_round = max(0, int(template.get("off_hand_attacks_per_round", 0)))
    entity.off_hand_hit_roll_modifier = int(template.get("off_hand_hit_roll_modifier", 0))
    entity.coin_reward = max(0, int(template.get("coin_reward", 0)))
    entity.experience_reward = max(0, int(template.get("experience_reward", 0)))
    entity.loot_items = _build_loot_items_from_template(template)
    entity.spawn_sequence = spawn_sequence
    entity.is_aggro = bool(template.get("is_aggro", False))
    entity.is_ally = bool(template.get("is_ally", False))
    entity.is_peaceful = bool(template.get("is_peaceful", False))
    entity.respawn = bool(template.get("respawn", True))
    entity.is_merchant = bool(template.get("is_merchant", False))
    entity.merchant_inventory_template_ids = [
        str(template_id).strip()
        for template_id in template.get("merchant_inventory_template_ids", [])
        if str(template_id).strip()
    ]
    entity.merchant_inventory = [
        {
            "template_id": str(stock_entry.get("template_id", "")).strip(),
            "infinite": bool(stock_entry.get("infinite", False)),
            "quantity": max(0, int(stock_entry.get("quantity", 1))),
        }
        for stock_entry in template.get("merchant_inventory", [])
        if isinstance(stock_entry, dict) and str(stock_entry.get("template_id", "")).strip()
    ]
    entity.merchant_buy_markup = max(0.1, float(template.get("merchant_buy_markup", 1.0)))
    entity.merchant_sell_ratio = max(0.0, min(1.0, float(template.get("merchant_sell_ratio", 0.5))))
    entity.pronoun_possessive = str(template.get("pronoun_possessive", "its")).strip().lower() or "its"
    entity.main_hand_weapon_template_id = str(template.get("main_hand_weapon_template_id", "")).strip()
    entity.off_hand_weapon_template_id = str(template.get("off_hand_weapon_template_id", "")).strip()
    entity.vigor = max(0, int(template.get("vigor", template.get("max_vigor", 0))))
    entity.max_vigor = max(0, int(template.get("max_vigor", 0)))
    entity.mana = max(0, int(template.get("mana", template.get("max_mana", 0))))
    entity.max_mana = max(0, int(template.get("max_mana", 0)))
    entity.skill_use_chance = max(0.0, min(1.0, float(template.get("skill_use_chance", 0.35))))
    entity.skill_ids = [str(skill_id).strip() for skill_id in template.get("skill_ids", []) if str(skill_id).strip()]
    entity.spell_use_chance = max(0.0, min(1.0, float(template.get("spell_use_chance", 0.25))))
    entity.spell_ids = [str(spell_id).strip() for spell_id in template.get("spell_ids", []) if str(spell_id).strip()]
    return entity


def _clear_entity_ids_from_combat_state(entity_ids: set[str]) -> None:
    if not entity_ids:
        return

    seen_sessions: set[int] = set()
    for session in list(connected_clients.values()) + list(active_character_sessions.values()):
        session_marker = id(session)
        if session_marker in seen_sessions:
            continue
        seen_sessions.add(session_marker)
        session.combat.engaged_entity_ids -= entity_ids


def reinitialize_zone(zone_id: str) -> int:
    zone = WORLD.zones.get(zone_id)
    if zone is None:
        return 0

    zone_room_ids = {room_id for room_id in zone.room_ids if room_id in WORLD.rooms}
    if not zone_room_ids:
        return 0

    removed_entity_ids: set[str] = set()
    for entity_id, entity in list(shared_world_entities.items()):
        if entity.room_id not in zone_room_ids:
            continue
        if not bool(getattr(entity, "respawn", False)):
            continue
        removed_entity_ids.add(entity_id)
        shared_world_entities.pop(entity_id, None)

    _clear_entity_ids_from_combat_state(removed_entity_ids)

    for corpse_id, corpse in list(shared_world_corpses.items()):
        if corpse.room_id in zone_room_ids:
            shared_world_corpses.pop(corpse_id, None)

    for room_id in zone_room_ids:
        shared_world_room_coin_piles.pop(room_id, None)
        shared_world_room_ground_items.pop(room_id, None)

    next_spawn_sequence = max((entity.spawn_sequence for entity in shared_world_entities.values()), default=0)
    spawned_count = 0

    for room_id in zone.room_ids:
        room = WORLD.rooms.get(room_id)
        if room is None:
            continue

        for npc_spawn in room.npcs:
            npc_id = str(npc_spawn.get("npc_id", "")).strip()
            if not npc_id:
                continue

            template = get_npc_template_by_id(npc_id)
            if template is None or not bool(template.get("respawn", True)):
                continue

            spawn_count = max(1, int(npc_spawn.get("count", 1)))
            for _ in range(spawn_count):
                next_spawn_sequence += 1
                entity = _build_entity_from_template(template, room.room_id, next_spawn_sequence)
                shared_world_entities[entity.entity_id] = entity
                spawned_count += 1

    for session in list(connected_clients.values()) + list(active_character_sessions.values()):
        session.entity_spawn_counter = max(session.entity_spawn_counter, next_spawn_sequence)

    return spawned_count


def _zone_has_active_players(zone_id: str) -> bool:
    zone = WORLD.zones.get(zone_id)
    if zone is None:
        return False

    zone_room_ids = {room_id for room_id in zone.room_ids if room_id in WORLD.rooms}
    if not zone_room_ids:
        return False

    seen_session_keys: set[str] = set()
    for session in list(active_character_sessions.values()) + list(connected_clients.values()):
        if not getattr(session, "is_authenticated", False):
            continue
        if bool(getattr(session, "disconnected_by_server", False)):
            continue

        session_key = session.player_state_key.strip().lower() or session.client_id.strip().lower()
        if session_key in seen_session_keys:
            continue
        seen_session_keys.add(session_key)

        if getattr(session.player, "current_room_id", "") in zone_room_ids:
            return True

    return False


def repopulate_game_hour_zones() -> None:
    for zone in WORLD.zones.values():
        repopulate_game_hours = max(0, int(getattr(zone, "repopulate_game_hours", 0)))
        if repopulate_game_hours <= 0:
            zone.pending_repopulation = False
            zone.game_hours_since_repopulation = 0
            continue

        if not zone.pending_repopulation:
            zone.game_hours_since_repopulation += 1
            if zone.game_hours_since_repopulation < repopulate_game_hours:
                continue
            zone.pending_repopulation = True

        if _zone_has_active_players(zone.zone_id):
            continue

        if zone.pending_repopulation:
            reinitialize_zone(zone.zone_id)
            zone.pending_repopulation = False
            zone.game_hours_since_repopulation = 0


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
                entity = _build_entity_from_template(template, room.room_id, session.entity_spawn_counter)
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
    entity = EntityState(entity_id, dummy_name, room_id, 40, 40)
    entity.power_level = 6
    entity.attacks_per_round = 1
    entity.coin_reward = 12
    entity.experience_reward = 10
    entity.spawn_sequence = next_spawn_sequence
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
    if bool(getattr(entity, "is_peaceful", False)):
        return _display_peaceful_warning(session, entity)

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
        _append_experience_gain_parts(session, entity, parts, build_part)

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