import asyncio
import random
import uuid

from assets import get_gear_template_by_id, get_item_template_by_id, get_npc_template_by_id, load_rooms
from combat_state import maybe_auto_engage_current_room
from corpse_labels import normalize_corpse_label_style
from inventory import build_equippable_item_from_template, build_misc_item_from_template, tick_item_decay_list, tick_item_decay_map
from models import ClientSession, EntityState, ItemState
from player_state_db import clear_player_interaction_flags, save_player_state
from session_registry import (
    active_character_sessions,
    connected_clients,
    shared_world_corpses,
    shared_world_entities,
    shared_world_flags,
    shared_world_room_coin_piles,
    shared_world_room_ground_items,
)
from targeting_entities import list_room_entities
from world import WORLD
from server_transport import send_outbound


def _roll_percent_chance(chance_percent: float) -> bool:
    return chance_percent > 0.0 and (random.random() * 100.0) < chance_percent


def _build_inventory_items_from_template(
    template: dict,
    excluded_template_ids: set[str] | None = None,
) -> list[ItemState]:
    inventory_items: list[ItemState] = []
    excluded_ids = {
        str(template_id).strip().lower()
        for template_id in (excluded_template_ids or set())
        if str(template_id).strip()
    }
    for raw_inventory_item in template.get("inventory_items", []):
        if not isinstance(raw_inventory_item, dict):
            continue

        template_id = str(raw_inventory_item.get("template_id", "")).strip()
        if not template_id:
            continue
        if template_id.lower() in excluded_ids:
            continue

        quantity = max(0, int(raw_inventory_item.get("quantity", 1)))
        if quantity <= 0:
            continue

        spawn_chance = max(0.0, min(100.0, float(raw_inventory_item.get("spawn_chance", 100.0))))
        if spawn_chance <= 0.0:
            continue

        gear_template = get_gear_template_by_id(template_id)
        item_template = get_item_template_by_id(template_id) if gear_template is None else None
        resolved_template = gear_template or item_template
        if resolved_template is None:
            continue

        for _ in range(quantity):
            if not _roll_percent_chance(spawn_chance):
                continue
            if gear_template is not None:
                inventory_item = build_equippable_item_from_template(
                    gear_template,
                    item_id=f"npc-item-{uuid.uuid4().hex[:8]}",
                )
            else:
                inventory_item = build_misc_item_from_template(
                    resolved_template,
                    item_id=f"npc-item-{uuid.uuid4().hex[:8]}",
                )
            inventory_items.append(inventory_item)
    return inventory_items


def _populate_room_ground_items_from_config(room) -> None:
    if room is None:
        return

    room_items = shared_world_room_ground_items.setdefault(room.room_id, {})
    for raw_room_item in room.items:
        template_id = str(raw_room_item.get("template_id", "")).strip()
        quantity = max(0, int(raw_room_item.get("count", 1)))
        if not template_id or quantity <= 0:
            continue

        gear_template = get_gear_template_by_id(template_id)
        item_template = get_item_template_by_id(template_id) if gear_template is None else None
        resolved_template = gear_template or item_template
        if resolved_template is None:
            continue

        for _ in range(quantity):
            if gear_template is not None:
                ground_item = build_equippable_item_from_template(
                    gear_template,
                    item_id=f"room-item-{uuid.uuid4().hex[:8]}",
                )
            else:
                ground_item = build_misc_item_from_template(
                    resolved_template,
                    item_id=f"room-item-{uuid.uuid4().hex[:8]}",
                )
            room_items[ground_item.item_id] = ground_item


def _count_room_npc_instances(room_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entity in shared_world_entities.values():
        if not getattr(entity, "is_alive", False):
            continue
        if str(getattr(entity, "room_id", "")).strip() != str(room_id).strip():
            continue

        npc_id = str(getattr(entity, "npc_id", "")).strip()
        if not npc_id:
            continue
        counts[npc_id] = counts.get(npc_id, 0) + 1
    return counts


def _template_triggers_auto_hostility(template: dict) -> bool:
    if bool(template.get("is_aggro", False)):
        return True
    return any(str(flag).strip() for flag in template.get("aggro_player_flags", []))


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
    entity.spawn_sequence = spawn_sequence
    entity.is_aggro = bool(template.get("is_aggro", False))
    entity.is_named = bool(template.get("is_named", False))
    entity.aggro_player_flags = [
        str(flag).strip().lower()
        for flag in template.get("aggro_player_flags", [])
        if str(flag).strip()
    ]
    entity.set_player_flags_on_hostile_action = [
        str(flag).strip().lower()
        for flag in template.get("set_player_flags_on_hostile_action", [])
        if str(flag).strip()
    ]
    entity.set_player_flags_on_death = [
        str(flag).strip().lower()
        for flag in template.get("set_player_flags_on_death", [])
        if str(flag).strip()
    ]
    entity.set_world_flags_on_death = [
        str(flag).strip().lower()
        for flag in template.get("set_world_flags_on_death", [])
        if str(flag).strip()
    ]
    entity.corpse_label_style = normalize_corpse_label_style(template.get("corpse_label_style", "generic"))
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
            "base_quantity": max(0, int(stock_entry.get("base_quantity", stock_entry.get("quantity", 1)))),
        }
        for stock_entry in template.get("merchant_inventory", [])
        if isinstance(stock_entry, dict) and str(stock_entry.get("template_id", "")).strip()
    ]
    entity.merchant_buy_markup = max(0.1, float(template.get("merchant_buy_markup", 1.0)))
    entity.merchant_sell_ratio = max(0.0, min(1.0, float(template.get("merchant_sell_ratio", 0.5))))
    entity.merchant_restock_game_hours = max(0, int(template.get("merchant_restock_game_hours", 0)))
    entity.merchant_restock_elapsed_hours = 0
    entity.pronoun_possessive = str(template.get("pronoun_possessive", "its")).strip().lower() or "its"
    main_hand_weapon = template.get("main_hand_weapon", {})
    if not isinstance(main_hand_weapon, dict):
        main_hand_weapon = {"template_id": str(template.get("main_hand_weapon_template_id", "")).strip()}
    off_hand_weapon = template.get("off_hand_weapon", {})
    if not isinstance(off_hand_weapon, dict):
        off_hand_weapon = {"template_id": str(template.get("off_hand_weapon_template_id", "")).strip()}

    main_hand_spawn_chance = max(0.0, min(100.0, float(main_hand_weapon.get("spawn_chance", 100.0))))
    off_hand_spawn_chance = max(0.0, min(100.0, float(off_hand_weapon.get("spawn_chance", 100.0))))
    entity.main_hand_weapon_template_id = (
        str(main_hand_weapon.get("template_id", "")).strip()
        if _roll_percent_chance(main_hand_spawn_chance)
        else ""
    )
    entity.main_hand_weapon_drop_on_death = max(0.0, min(100.0, float(main_hand_weapon.get("drop_on_death", 0.0))))
    entity.off_hand_weapon_template_id = (
        str(off_hand_weapon.get("template_id", "")).strip()
        if _roll_percent_chance(off_hand_spawn_chance)
        else ""
    )
    entity.off_hand_weapon_drop_on_death = max(0.0, min(100.0, float(off_hand_weapon.get("drop_on_death", 0.0))))
    entity.inventory_items = _build_inventory_items_from_template(
        template,
        excluded_template_ids={
            template_id
            for template_id in (entity.main_hand_weapon_template_id, entity.off_hand_weapon_template_id)
            if template_id
        },
    )
    entity.vigor = max(0, int(template.get("vigor", template.get("max_vigor", 0))))
    entity.max_vigor = max(0, int(template.get("max_vigor", 0)))
    entity.mana = max(0, int(template.get("mana", template.get("max_mana", 0))))
    entity.max_mana = max(0, int(template.get("max_mana", 0)))
    entity.skill_use_chance = max(0.0, min(1.0, float(template.get("skill_use_chance", 0.35))))
    entity.skill_ids = [str(skill_id).strip() for skill_id in template.get("skill_ids", []) if str(skill_id).strip()]
    entity.spell_use_chance = max(0.0, min(1.0, float(template.get("spell_use_chance", 0.25))))
    entity.spell_ids = [str(spell_id).strip() for spell_id in template.get("spell_ids", []) if str(spell_id).strip()]
    entity.wander_chance = max(0.0, min(1.0, float(template.get("wander_chance", 0.0))))
    entity.wander_room_ids = [str(rid).strip() for rid in template.get("wander_room_ids", []) if str(rid).strip()]
    return entity


def _iter_unique_sessions():
    seen_sessions: set[int] = set()
    for session in list(connected_clients.values()) + list(active_character_sessions.values()):
        session_marker = id(session)
        if session_marker in seen_sessions:
            continue
        seen_sessions.add(session_marker)
        yield session


def _clear_entity_ids_from_combat_state(entity_ids: set[str]) -> None:
    if not entity_ids:
        return

    for session in _iter_unique_sessions():
        session.combat.engaged_entity_ids -= entity_ids


def _evaluate_auto_aggro_for_room_players(room_ids: set[str]) -> None:
    if not room_ids:
        return

    seen_session_keys: set[str] = set()
    for session in _iter_unique_sessions():
        if not getattr(session, "is_authenticated", False):
            continue
        if not getattr(session, "is_connected", False) or bool(getattr(session, "disconnected_by_server", False)):
            continue

        room_id = str(getattr(session.player, "current_room_id", "")).strip()
        if room_id not in room_ids:
            continue

        session_key = str(getattr(session, "player_state_key", "")).strip().lower() or str(getattr(session, "client_id", "")).strip().lower()
        if session_key in seen_session_keys:
            continue
        seen_session_keys.add(session_key)
        maybe_auto_engage_current_room(session)


def _clear_zone_player_flags(zone) -> None:
    flags_to_clear = {
        str(flag).strip().lower()
        for flag in getattr(zone, "reset_player_flags", [])
        if str(flag).strip()
    }
    if not flags_to_clear:
        return

    clear_player_interaction_flags(flags_to_clear)
    for session in _iter_unique_sessions():
        interaction_flags = dict(getattr(session.player, "interaction_flags", {}) or {})
        changed = False
        for flag in flags_to_clear:
            if flag in interaction_flags:
                interaction_flags.pop(flag, None)
                changed = True
        if not changed:
            continue
        session.player.interaction_flags = interaction_flags
        if getattr(session, "is_authenticated", False) and str(getattr(session, "player_state_key", "")).strip():
            save_player_state(session)


def _clear_zone_world_flags(zone) -> None:
    flags_to_clear = {
        str(flag).strip().lower()
        for flag in getattr(zone, "reset_world_flags", [])
        if str(flag).strip()
    }
    if not flags_to_clear:
        return

    for flag in flags_to_clear:
        shared_world_flags.discard(flag)


def _reset_zone_container_templates(zone) -> None:
    template_ids = {
        str(template_id).strip().lower()
        for template_id in getattr(zone, "reset_container_template_ids", [])
        if str(template_id).strip()
    }
    if not template_ids:
        return

    for room_items in shared_world_room_ground_items.values():
        for item_id, item in list(room_items.items()):
            template_id = str(getattr(item, "template_id", "")).strip().lower()
            if template_id not in template_ids:
                continue
            template = get_item_template_by_id(template_id)
            if template is None:
                continue
            room_items[item_id] = build_misc_item_from_template(template, item_id=item_id)


def _reset_zone_room_exit_states(zone) -> None:
    zone_room_ids = {room_id for room_id in getattr(zone, "room_ids", []) if room_id in WORLD.rooms}
    if not zone_room_ids:
        return

    load_rooms.cache_clear()
    fresh_rooms_by_id = {
        str(room_data.get("room_id", "")).strip(): room_data
        for room_data in load_rooms()
        if isinstance(room_data, dict)
    }

    linked_room_ids = set(zone_room_ids)
    for room_id, room in WORLD.rooms.items():
        for destination_room_id in getattr(room, "exits", {}).values():
            if destination_room_id in zone_room_ids:
                linked_room_ids.add(room_id)
                break

    for room_id in linked_room_ids:
        room = WORLD.rooms.get(room_id)
        fresh_room = fresh_rooms_by_id.get(room_id)
        if room is None or fresh_room is None:
            continue

        room.exits = dict(fresh_room.get("exits", {}))
        room.exit_details = [dict(exit_detail) for exit_detail in fresh_room.get("exit_details", [])]


def process_world_item_game_hour_tick() -> None:
    for room_items in shared_world_room_ground_items.values():
        tick_item_decay_map(room_items)

    for corpse in shared_world_corpses.values():
        tick_item_decay_map(corpse.loot_items)

    for entity in shared_world_entities.values():
        tick_item_decay_list(entity.inventory_items)


def _item_matches_template_ids(item: ItemState, template_ids: set[str]) -> bool:
    if str(getattr(item, "template_id", "")).strip().lower() in template_ids:
        return True

    nested_items = getattr(item, "container_items", {})
    if not isinstance(nested_items, dict):
        return False

    return any(_item_matches_template_ids(nested_item, template_ids) for nested_item in nested_items.values())


def _item_map_contains_template_ids(item_map: dict[str, ItemState], template_ids: set[str]) -> bool:
    return any(_item_matches_template_ids(item, template_ids) for item in item_map.values())


def _item_list_contains_template_ids(items: list[ItemState], template_ids: set[str]) -> bool:
    return any(_item_matches_template_ids(item, template_ids) for item in items)


def _zone_repopulation_is_blocked(zone) -> bool:
    template_ids = {
        str(template_id).strip().lower()
        for template_id in getattr(zone, "repopulation_blocking_item_template_ids", [])
        if str(template_id).strip()
    }
    if not template_ids:
        zone.repopulation_block_remaining_hours = 0
        return False

    cooldown_hours = max(0, int(getattr(zone, "repopulation_block_cooldown_game_hours", 0)))

    blocker_exists = False
    for session in _iter_unique_sessions():
        if _item_map_contains_template_ids(getattr(session, "inventory_items", {}), template_ids):
            blocker_exists = True
            break
        equipment = getattr(getattr(session, "equipment", None), "equipped_items", {})
        if _item_map_contains_template_ids(equipment, template_ids):
            blocker_exists = True
            break

    if not blocker_exists:
        for room_items in shared_world_room_ground_items.values():
            if _item_map_contains_template_ids(room_items, template_ids):
                blocker_exists = True
                break

    if not blocker_exists:
        for corpse in shared_world_corpses.values():
            if _item_map_contains_template_ids(corpse.loot_items, template_ids):
                blocker_exists = True
                break

    if not blocker_exists:
        for entity in shared_world_entities.values():
            if _item_list_contains_template_ids(getattr(entity, "inventory_items", []), template_ids):
                blocker_exists = True
                break

    if blocker_exists:
        zone.repopulation_block_remaining_hours = cooldown_hours
        return True

    remaining_hours = max(0, int(getattr(zone, "repopulation_block_remaining_hours", 0)))
    if remaining_hours <= 0:
        return False

    zone.repopulation_block_remaining_hours = remaining_hours - 1
    return True


def reinitialize_zone(zone_id: str, *, force: bool = False) -> int:
    zone = WORLD.zones.get(zone_id)
    if zone is None:
        return 0

    if not force and _zone_has_active_players(zone_id):
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

    _clear_zone_player_flags(zone)
    _clear_zone_world_flags(zone)
    _reset_zone_container_templates(zone)
    _reset_zone_room_exit_states(zone)

    next_spawn_sequence = max((entity.spawn_sequence for entity in shared_world_entities.values()), default=0)
    spawned_count = 0
    hostile_spawn_room_ids: set[str] = set()

    for room_id in zone.room_ids:
        room = WORLD.rooms.get(room_id)
        if room is None:
            continue

        _populate_room_ground_items_from_config(room)

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
                if _template_triggers_auto_hostility(template):
                    hostile_spawn_room_ids.add(room.room_id)

    for session in list(connected_clients.values()) + list(active_character_sessions.values()):
        session.entity_spawn_counter = max(session.entity_spawn_counter, next_spawn_sequence)

    _evaluate_auto_aggro_for_room_players(hostile_spawn_room_ids)
    return spawned_count


def _broadcast_zone_flag_spawn_announcement(zone_id: str, message: str) -> None:
    cleaned_message = str(message).strip()
    if not cleaned_message:
        return

    zone = WORLD.zones.get(zone_id)
    if zone is None:
        return

    zone_room_ids = {room_id for room_id in zone.room_ids if room_id in WORLD.rooms}
    if not zone_room_ids:
        return

    from display_core import build_part
    from display_feedback import display_command_result

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    for session in _iter_unique_sessions():
        if not getattr(session, "is_authenticated", False):
            continue
        if not getattr(session, "is_connected", False) or bool(getattr(session, "disconnected_by_server", False)):
            continue
        if getattr(session.player, "current_room_id", "") not in zone_room_ids:
            continue

        notification = display_command_result(session, [
            build_part(cleaned_message, "feedback.warning", True),
        ])
        loop.create_task(send_outbound(session.websocket, notification))


def process_zone_flag_spawns() -> int:
    """Spawn NPCs whose flag conditions are now satisfied.

    Called immediately after an entity death that sets world flags.  For each
    zone flag_spawn rule, if all required_world_flags are set and none of the
    excluded_world_flags are set, and no matching NPC is already alive in the
    target room, the NPC is spawned.
    """
    spawned_count = 0
    hostile_spawn_room_ids: set[str] = set()
    next_spawn_sequence = max(
        (entity.spawn_sequence for entity in shared_world_entities.values()), default=0
    )

    for zone in WORLD.zones.values():
        flag_spawns: list[dict] = getattr(zone, "flag_spawns", [])
        if not flag_spawns:
            continue

        for spawn_rule in flag_spawns:
            required_flags: list[str] = spawn_rule.get("required_world_flags", [])
            excluded_flags: list[str] = spawn_rule.get("excluded_world_flags", [])

            if not all(flag in shared_world_flags for flag in required_flags):
                continue
            if any(flag in shared_world_flags for flag in excluded_flags):
                continue

            room_id: str = spawn_rule.get("room_id", "")
            npc_id: str = spawn_rule.get("npc_id", "")
            count: int = max(1, int(spawn_rule.get("count", 1)))
            announcement_message = str(spawn_rule.get("announcement_message", "")).strip()

            if room_id not in WORLD.rooms:
                continue

            already_alive = any(
                getattr(entity, "npc_id", "") == npc_id
                and entity.room_id == room_id
                and getattr(entity, "is_alive", False)
                for entity in shared_world_entities.values()
            )
            if already_alive:
                continue

            template = get_npc_template_by_id(npc_id)
            if template is None:
                continue

            spawned_for_rule = 0
            for _ in range(count):
                next_spawn_sequence += 1
                entity = _build_entity_from_template(template, room_id, next_spawn_sequence)
                shared_world_entities[entity.entity_id] = entity
                spawned_count += 1
                spawned_for_rule += 1
                if _template_triggers_auto_hostility(template):
                    hostile_spawn_room_ids.add(room_id)

            if spawned_for_rule > 0 and announcement_message:
                _broadcast_zone_flag_spawn_announcement(zone.zone_id, announcement_message)

    if spawned_count > 0:
        for session in list(connected_clients.values()) + list(active_character_sessions.values()):
            session.entity_spawn_counter = max(session.entity_spawn_counter, next_spawn_sequence)

    _evaluate_auto_aggro_for_room_players(hostile_spawn_room_ids)
    return spawned_count


def _zone_has_active_players(zone_id: str) -> bool:
    zone = WORLD.zones.get(zone_id)
    if zone is None:
        return False

    zone_room_ids = {room_id for room_id in zone.room_ids if room_id in WORLD.rooms}
    if not zone_room_ids:
        return False

    for session in _iter_unique_sessions():
        if not getattr(session, "is_authenticated", False):
            continue
        if bool(getattr(session, "disconnected_by_server", False)):
            continue

        if getattr(session.player, "current_room_id", "") in zone_room_ids:
            return True

    return False


def repopulate_game_hour_zones() -> None:
    for zone in WORLD.zones.values():
        repopulate_game_hours = max(0, int(getattr(zone, "repopulate_game_hours", 0)))
        if repopulate_game_hours <= 0:
            zone.pending_repopulation = False
            zone.game_hours_since_repopulation = 0
            zone.repopulation_block_remaining_hours = 0
            continue

        if not zone.pending_repopulation:
            zone.game_hours_since_repopulation += 1
            if zone.game_hours_since_repopulation < repopulate_game_hours:
                continue
            zone.pending_repopulation = True

        if _zone_repopulation_is_blocked(zone):
            continue

        if _zone_has_active_players(zone.zone_id):
            continue

        if zone.pending_repopulation:
            reinitialize_zone(zone.zone_id)
            zone.pending_repopulation = False
            zone.game_hours_since_repopulation = 0


def initialize_shared_world_state() -> int:
    next_spawn_sequence = max((entity.spawn_sequence for entity in shared_world_entities.values()), default=0)
    spawned_count = 0

    for room in WORLD.rooms.values():
        if room.room_id not in shared_world_room_ground_items:
            _populate_room_ground_items_from_config(room)

        room_npc_counts = _count_room_npc_instances(room.room_id)
        for npc_spawn in room.npcs:
            npc_id = str(npc_spawn.get("npc_id", "")).strip()
            if not npc_id:
                continue

            template = get_npc_template_by_id(npc_id)
            if template is None:
                continue

            spawn_count = max(1, int(npc_spawn.get("count", 1)))
            current_count = room_npc_counts.get(npc_id, 0)
            missing_count = max(0, spawn_count - current_count)
            for _ in range(missing_count):
                next_spawn_sequence += 1
                entity = _build_entity_from_template(template, room.room_id, next_spawn_sequence)
                shared_world_entities[entity.entity_id] = entity
                room_npc_counts[npc_id] = room_npc_counts.get(npc_id, 0) + 1
                spawned_count += 1

    for session in list(connected_clients.values()) + list(active_character_sessions.values()):
        session.entity_spawn_counter = max(session.entity_spawn_counter, next_spawn_sequence)

    return spawned_count


def initialize_session_entities(session: ClientSession) -> None:
    next_entity_spawn_sequence = max((entity.spawn_sequence for entity in session.entities.values()), default=0)
    next_corpse_spawn_sequence = max((corpse.spawn_sequence for corpse in session.corpses.values()), default=0)
    session.entity_spawn_counter = max(session.entity_spawn_counter, next_entity_spawn_sequence)
    session.corpse_spawn_counter = max(session.corpse_spawn_counter, next_corpse_spawn_sequence)


def spawn_dummy(session: ClientSession) -> dict:
    from display_core import build_part
    from display_feedback import display_command_result

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
        build_part("Spawned ", "feedback.text"),
        build_part(entity.name, bold=True),
        build_part(" in this room.", "feedback.text"),
    ])
