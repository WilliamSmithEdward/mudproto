import uuid

from assets import get_gear_template_by_id, get_item_template_by_id, get_npc_template_by_id
from inventory import build_equippable_item_from_template, build_misc_item_from_template
from models import ClientSession, EntityState, ItemState
from session_registry import (
    active_character_sessions,
    connected_clients,
    shared_world_corpses,
    shared_world_entities,
    shared_world_room_coin_piles,
    shared_world_room_ground_items,
)
from targeting_entities import list_room_entities
from world import WORLD


def _build_loot_items_from_template(template: dict) -> list[ItemState]:
    loot_items: list[ItemState] = []
    for loot_template in template.get("loot_items", []):
        template_id = str(loot_template.get("template_id", "")).strip()
        resolved_item_template = get_item_template_by_id(template_id) if template_id else None
        if resolved_item_template is not None:
            loot_items.append(
                build_misc_item_from_template(
                    resolved_item_template,
                    item_id=f"loot-{uuid.uuid4().hex[:8]}",
                )
            )
            continue

        loot_items.append(ItemState(
            item_id=f"loot-{uuid.uuid4().hex[:8]}",
            name=str(loot_template.get("name", "Loot")).strip() or "Loot",
            template_id=template_id,
            description=str(loot_template.get("description", "")),
            keywords=list(loot_template.get("keywords", [])),
        ))
    return loot_items


def _build_inventory_items_from_template(template: dict) -> list[ItemState]:
    inventory_items: list[ItemState] = []
    for raw_inventory_item in template.get("inventory_items", []):
        if not isinstance(raw_inventory_item, dict):
            continue

        template_id = str(raw_inventory_item.get("template_id", "")).strip()
        if not template_id:
            continue

        quantity = max(0, int(raw_inventory_item.get("quantity", 1)))
        if quantity <= 0:
            continue

        gear_template = get_gear_template_by_id(template_id)
        item_template = get_item_template_by_id(template_id) if gear_template is None else None
        resolved_template = gear_template or item_template
        if resolved_template is None:
            continue

        for _ in range(quantity):
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
    entity.inventory_items = _build_inventory_items_from_template(template)
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
        _populate_room_ground_items_from_config(room)
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
        build_part("Spawned ", "bright_white"),
        build_part(entity.name, bold=True),
        build_part(" in this room.", "bright_white"),
    ])
