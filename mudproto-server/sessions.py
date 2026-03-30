import asyncio
import random
import uuid

from assets import load_attributes, get_default_player_class, get_equipment_template_by_id, get_player_class_by_id
from models import ClientSession, QueuedCommand
from player_state_db import save_player_state
from protocol import utc_now_iso
from settings import GAME_TICK_INTERVAL_SECONDS, MAX_QUEUED_COMMANDS

connected_clients: dict[str, ClientSession] = {}
active_character_sessions: dict[str, ClientSession] = {}
offline_character_tasks: dict[str, asyncio.Task] = {}

OFFLINE_LOOP_SLEEP_SECONDS = 0.5
OFFLINE_FLEE_INTERVAL_SECONDS = 2.0
OFFLINE_SAFE_HOURS_TO_DISCONNECT = 5


def ensure_player_attributes(session: ClientSession) -> None:
    configured_attribute_ids = [
        str(attribute.get("attribute_id", "")).strip().lower()
        for attribute in load_attributes()
        if str(attribute.get("attribute_id", "")).strip()
    ]

    current_ranges: dict[str, dict[str, int]] = {}
    if session.player.class_id.strip():
        player_class = get_player_class_by_id(session.player.class_id)
        if player_class is not None:
            raw_ranges = player_class.get("attribute_ranges", {})
            if isinstance(raw_ranges, dict):
                for attribute_id in configured_attribute_ids:
                    raw_range = raw_ranges.get(attribute_id, {})
                    if isinstance(raw_range, dict):
                        current_ranges[attribute_id] = {
                            "min": int(raw_range.get("min", 0)),
                            "max": int(raw_range.get("max", 0)),
                        }

    merged: dict[str, int] = {}
    for attribute_id in configured_attribute_ids:
        if attribute_id in session.player.attributes:
            merged[attribute_id] = int(session.player.attributes[attribute_id])
            continue

        attribute_range = current_ranges.get(attribute_id)
        if attribute_range is None:
            merged[attribute_id] = 0
            continue

        merged[attribute_id] = int(attribute_range.get("min", 0))

    for attribute_id, value in session.player.attributes.items():
        if attribute_id in merged:
            continue
        merged[attribute_id] = int(value)

    session.player.attributes = merged


def _grant_starting_equipment_from_template(session: ClientSession, template: dict) -> None:
    from equipment import HAND_MAIN, HAND_OFF, equip_item, wear_item

    existing_template_ids = {item.template_id for item in session.equipment.items.values()}
    existing_template_ids.update(item.template_id for item in session.equipment.equipped_items.values())
    template_id = str(template.get("template_id", "")).strip()
    if not template_id or template_id in existing_template_ids:
        return

    item_id = f"item-{uuid.uuid4().hex[:8]}"
    from models import EquipmentItemState
    item = EquipmentItemState(
        item_id=item_id,
        template_id=template_id,
        name=str(template.get("name", "Item")).strip() or "Item",
        slot=str(template.get("slot", "")).strip(),
        description=str(template.get("description", "")),
        keywords=list(template.get("keywords", [])),
        weapon_type=str(template.get("weapon_type", "unarmed")).strip().lower() or "unarmed",
        preferred_hand=str(template.get("preferred_hand", "main_hand")).strip().lower() or "main_hand",
        damage_dice_count=int(template.get("damage_dice_count", 0)),
        damage_dice_sides=int(template.get("damage_dice_sides", 0)),
        damage_roll_modifier=int(template.get("damage_roll_modifier", 0)),
        hit_roll_modifier=int(template.get("hit_roll_modifier", 0)),
        attack_damage_bonus=int(template.get("attack_damage_bonus", 0)),
        attacks_per_round_bonus=int(template.get("attacks_per_round_bonus", 0)),
        armor_class_bonus=int(template.get("armor_class_bonus", 0)),
        wear_slots=[str(slot).strip().lower() for slot in template.get("wear_slots", []) if str(slot).strip()],
    )
    if item.wear_slots:
        item.wear_slot = item.wear_slots[0]
    session.equipment.items[item_id] = item

    if not bool(template.get("equip_on_grant", False)):
        return

    if item.slot == "weapon":
        target_hand = HAND_OFF if item.preferred_hand == HAND_OFF else HAND_MAIN
        equip_item(session, item, target_hand)
        return

    if item.slot == "armor":
        wear_item(session, item)


def apply_player_class(session: ClientSession, class_id: str | None = None, *, roll_attributes: bool = False) -> None:
    player_class = get_default_player_class()
    if class_id is not None:
        matched_class = get_player_class_by_id(class_id)
        if matched_class is not None:
            player_class = matched_class

    session.player.class_id = str(player_class.get("class_id", "")).strip()

    if roll_attributes:
        raw_ranges = player_class.get("attribute_ranges", {})
        rolled_attributes: dict[str, int] = {}
        if isinstance(raw_ranges, dict):
            for attribute in load_attributes():
                attribute_id = str(attribute.get("attribute_id", "")).strip().lower()
                if not attribute_id:
                    continue

                raw_range = raw_ranges.get(attribute_id, {})
                if not isinstance(raw_range, dict):
                    continue

                min_value = int(raw_range.get("min", 0))
                max_value = int(raw_range.get("max", 0))
                rolled_attributes[attribute_id] = random.randint(min_value, max_value)

        session.player.attributes = rolled_attributes
    else:
        ensure_player_attributes(session)

    for template_id in player_class.get("starting_equipment_template_ids", []):
        template = get_equipment_template_by_id(str(template_id))
        if template is None:
            continue
        _grant_starting_equipment_from_template(session, template)

    known_spell_ids = {spell_id.strip().lower() for spell_id in session.known_spell_ids if spell_id.strip()}
    for spell_id in player_class.get("starting_spell_ids", []):
        normalized_spell_id = str(spell_id).strip().lower()
        if not normalized_spell_id or normalized_spell_id in known_spell_ids:
            continue
        session.known_spell_ids.append(str(spell_id).strip())
        known_spell_ids.add(normalized_spell_id)

    known_skill_ids = {skill_id.strip().lower() for skill_id in session.known_skill_ids if skill_id.strip()}
    for skill_id in player_class.get("starting_skill_ids", []):
        normalized_skill_id = str(skill_id).strip().lower()
        if not normalized_skill_id or normalized_skill_id in known_skill_ids:
            continue
        session.known_skill_ids.append(str(skill_id).strip())
        known_skill_ids.add(normalized_skill_id)


def get_connection_count() -> int:
    return sum(1 for session in connected_clients.values() if session.is_connected)


def register_client(client_id: str, websocket) -> ClientSession:
    session = ClientSession(
        client_id=client_id,
        websocket=websocket,
        connected_at=utc_now_iso()
    )
    session.is_connected = True
    connected_clients[client_id] = session
    return session


def unregister_client(client_id: str) -> None:
    connected_clients.pop(client_id, None)


def get_active_character_session(character_key: str) -> ClientSession | None:
    normalized_key = character_key.strip().lower()
    if not normalized_key:
        return None
    return active_character_sessions.get(normalized_key)


def _copy_runtime_state(source: ClientSession, target: ClientSession) -> None:
    target.player = source.player
    target.player_combat = source.player_combat
    target.status = source.status
    target.combat = source.combat
    target.equipment = source.equipment
    target.entities = source.entities
    target.entity_spawn_counter = source.entity_spawn_counter
    target.corpses = source.corpses
    target.corpse_spawn_counter = source.corpse_spawn_counter
    target.room_coin_piles = source.room_coin_piles
    target.room_ground_items = source.room_ground_items
    target.inventory_items = source.inventory_items
    target.known_spell_ids = source.known_spell_ids
    target.known_skill_ids = source.known_skill_ids
    target.active_support_effects = source.active_support_effects
    target.next_game_tick_monotonic = source.next_game_tick_monotonic
    target.next_non_combat_support_round_monotonic = source.next_non_combat_support_round_monotonic


def stop_offline_character_processing(character_key: str) -> None:
    normalized_key = character_key.strip().lower()
    if not normalized_key:
        return

    task = offline_character_tasks.pop(normalized_key, None)
    if task is not None:
        task.cancel()


def hydrate_session_from_active_character(target_session: ClientSession, character_key: str) -> bool:
    normalized_key = character_key.strip().lower()
    if not normalized_key:
        return False

    existing = active_character_sessions.get(normalized_key)
    if existing is None or existing.disconnected_by_server:
        return False

    stop_offline_character_processing(normalized_key)
    if existing.scheduler_task is not None:
        existing.scheduler_task.cancel()

    _copy_runtime_state(existing, target_session)
    active_character_sessions.pop(normalized_key, None)
    return True


def register_authenticated_character_session(session: ClientSession) -> None:
    normalized_key = session.player_state_key.strip().lower()
    if not normalized_key:
        return

    stop_offline_character_processing(normalized_key)
    session.player_state_key = normalized_key
    session.disconnected_by_server = False
    session.is_connected = True
    active_character_sessions[normalized_key] = session


async def _offline_character_loop(character_key: str, session: ClientSession) -> None:
    from combat import end_combat, get_engaged_entity, process_game_hour_tick, resolve_combat_round

    safe_hours = 0
    previous_hit_points = session.status.hit_points
    next_flee_attempt_monotonic = 0.0
    loop = asyncio.get_running_loop()
    next_hour_tick_monotonic = loop.time() + GAME_TICK_INTERVAL_SECONDS

    try:
        while True:
            await asyncio.sleep(OFFLINE_LOOP_SLEEP_SECONDS)

            current_active = active_character_sessions.get(character_key)
            if current_active is not session:
                break
            if session.is_connected:
                break

            now = loop.time()

            if session.combat.next_round_monotonic is not None and now >= session.combat.next_round_monotonic:
                resolve_combat_round(session)

            engaged = get_engaged_entity(session) is not None
            if engaged and now >= next_flee_attempt_monotonic:
                from commands import flee

                flee(session)
                next_flee_attempt_monotonic = now + OFFLINE_FLEE_INTERVAL_SECONDS

            if now >= next_hour_tick_monotonic:
                process_game_hour_tick(session)
                save_player_state(session)

                hp_now = session.status.hit_points
                took_damage = hp_now < previous_hit_points
                engaged_after_tick = get_engaged_entity(session) is not None

                if not engaged_after_tick and not took_damage:
                    safe_hours += 1
                else:
                    safe_hours = 0

                previous_hit_points = hp_now
                while next_hour_tick_monotonic <= now:
                    next_hour_tick_monotonic += GAME_TICK_INTERVAL_SECONDS

                if safe_hours >= OFFLINE_SAFE_HOURS_TO_DISCONNECT:
                    session.disconnected_by_server = True
                    session.is_connected = False
                    if session.login_room_id.strip():
                        session.player.current_room_id = session.login_room_id.strip()
                    end_combat(session)
                    save_player_state(session)
                    active_character_sessions.pop(character_key, None)
                    break
    finally:
        current = offline_character_tasks.get(character_key)
        if current is not None and current.done():
            offline_character_tasks.pop(character_key, None)


def start_offline_character_processing(session: ClientSession) -> None:
    normalized_key = session.player_state_key.strip().lower()
    if not session.is_authenticated or not normalized_key:
        return

    session.is_connected = False
    if active_character_sessions.get(normalized_key) is not session:
        active_character_sessions[normalized_key] = session

    existing_task = offline_character_tasks.get(normalized_key)
    if existing_task is not None and not existing_task.done():
        return

    offline_character_tasks[normalized_key] = asyncio.create_task(_offline_character_loop(normalized_key, session))


def handle_client_disconnect(session: ClientSession) -> None:
    unregister_client(session.client_id)
    if session.is_authenticated:
        start_offline_character_processing(session)


def touch_session(session: ClientSession) -> None:
    session.last_message_at = utc_now_iso()


def is_session_lagged(session: ClientSession) -> bool:
    if session.lag_until_monotonic is None:
        return False

    return asyncio.get_running_loop().time() < session.lag_until_monotonic


def get_remaining_lag_seconds(session: ClientSession) -> float:
    if session.lag_until_monotonic is None:
        return 0.0

    remaining = session.lag_until_monotonic - asyncio.get_running_loop().time()
    return max(0.0, remaining)


def apply_lag(session: ClientSession, duration_seconds: float) -> None:
    if duration_seconds <= 0:
        return

    now = asyncio.get_running_loop().time()
    base = max(now, session.lag_until_monotonic or now)
    session.lag_until_monotonic = base + duration_seconds


def enqueue_command(session: ClientSession, command_text: str) -> tuple[bool, str]:
    if len(session.command_queue) >= MAX_QUEUED_COMMANDS:
        return False, "Command queue is full."

    session.command_queue.append(QueuedCommand(
        command_text=command_text,
        received_at_iso=utc_now_iso()
    ))
    return True, "Command queued."