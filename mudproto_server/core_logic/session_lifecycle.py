import asyncio

from combat_state import maybe_auto_engage_current_room
from display_core import build_line, build_part
from display_feedback import display_error
from display_room import display_room
from grammar import normalize_player_gender
from inventory import hydrate_misc_item_from_template
from models import ClientSession
from room_actions import prepend_room_enter_communications
from player_resources import clamp_player_resources_to_caps
from player_state_db import clear_transient_interaction_flags_for_session, load_player_state, save_player_state
from session_bootstrap import apply_player_class, ensure_player_attributes
from session_registry import (
    active_character_sessions,
    attach_session_to_shared_world,
    offline_character_tasks,
    unregister_client,
)
from settings import (
    GAME_TICK_INTERVAL_SECONDS,
    OFFLINE_FLEE_INTERVAL_SECONDS,
    OFFLINE_LOOP_SLEEP_SECONDS,
    OFFLINE_SAFE_HOURS_TO_DISCONNECT,
)
from world import get_room


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

    # Keep world state shared for all sessions.
    attach_session_to_shared_world(target)


def stop_offline_character_processing(character_key: str) -> None:
    normalized_key = character_key.strip().lower()
    if not normalized_key:
        return

    task = offline_character_tasks.pop(normalized_key, None)
    if task is not None:
        task.cancel()


def purge_nonpersistent_items(session: ClientSession, *, reason: str = "disconnect") -> int:
    removed_item_ids: set[str] = set()

    for item_id, item in list(session.inventory_items.items()):
        hydrate_misc_item_from_template(item)
        if bool(getattr(item, "persistent", True)):
            continue
        session.inventory_items.pop(item_id, None)
        removed_item_ids.add(item_id)

    for item_id, item in list(session.equipment.equipped_items.items()):
        hydrate_misc_item_from_template(item)
        if bool(getattr(item, "persistent", True)):
            continue
        session.equipment.equipped_items.pop(item_id, None)
        removed_item_ids.add(item_id)
        if session.equipment.equipped_main_hand_id == item_id:
            session.equipment.equipped_main_hand_id = None
        if session.equipment.equipped_off_hand_id == item_id:
            session.equipment.equipped_off_hand_id = None
        for wear_slot, worn_item_id in list(session.equipment.worn_item_ids.items()):
            if worn_item_id == item_id:
                session.equipment.worn_item_ids.pop(wear_slot, None)

    return len(removed_item_ids)


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


def complete_login(session: ClientSession, character_record: dict, *, is_new_character: bool) -> dict | list[dict]:
    character_key = str(character_record.get("character_key", "")).strip()
    character_name = str(character_record.get("character_name", "")).strip()
    class_id = str(character_record.get("class_id", "")).strip()
    login_room_id = str(character_record.get("login_room_id", "")).strip() or "start"
    session.player.gender = normalize_player_gender(
        character_record.get("gender", session.player.gender),
        allow_unspecified=True,
    ) or "unspecified"

    session.player_state_key = character_key
    session.authenticated_character_name = character_name
    session.login_room_id = login_room_id
    session.pending_character_name = ""
    session.pending_password = ""
    session.pending_gender = ""

    resumed_from_active = hydrate_session_from_active_character(session, character_key)

    loaded_state = False
    if not resumed_from_active:
        loaded_state = load_player_state(session, player_key=character_key)
        if not loaded_state:
            apply_player_class(session, class_id, roll_attributes=True, initialize_progression=True)
        elif class_id:
            session.player.class_id = class_id

        ensure_player_attributes(session)
        session.player.current_room_id = login_room_id
    else:
        ensure_player_attributes(session)

    removed_nonpersistent_count = purge_nonpersistent_items(session, reason="login_sanitization")
    cleared_transient_flags = clear_transient_interaction_flags_for_session(session)
    clamp_player_resources_to_caps(session)

    session.is_authenticated = True
    session.is_connected = True
    session.disconnected_by_server = False
    session.auth_stage = "authenticated"
    register_authenticated_character_session(session)

    if (
        (not resumed_from_active and not loaded_state)
        or is_new_character
        or removed_nonpersistent_count > 0
        or cleared_transient_flags > 0
    ):
        save_player_state(session, player_key=character_key)

    login_room = get_room(session.player.current_room_id)
    if login_room is None:
        session.player.current_room_id = "start"
        login_room = get_room("start")

    if login_room is None:
        return display_error("Login room is not configured.", session)

    room_display = display_room(session, login_room)
    payload = room_display.get("payload") if isinstance(room_display, dict) else None
    if isinstance(payload, dict):
        lines = payload.get("lines")
        if isinstance(lines, list):
            greeting = "Character created" if is_new_character else "Welcome back"
            payload["lines"] = [
                build_line(
                    build_part(f"{greeting}, ", "bright_white"),
                    build_part(character_name, "bright_green", True),
                    build_part(".", "bright_white"),
                ),
                [],
            ] + lines
    prepend_room_enter_communications(room_display, session, login_room.room_id)

    maybe_auto_engage_current_room(session)
    return room_display


async def _offline_character_loop(character_key: str, session: ClientSession) -> None:
    from battle_round_ticks import process_non_combat_support_round
    from combat_state import end_combat, get_engaged_entity
    from game_hour_ticks import process_game_hour_tick

    safe_hours = 0
    previous_hit_points = session.status.hit_points
    next_flee_attempt_monotonic = 0.0
    loop = asyncio.get_running_loop()
    next_hour_tick_monotonic = session.next_game_tick_monotonic
    if next_hour_tick_monotonic is None:
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

            process_non_combat_support_round(session)

            engaged = get_engaged_entity(session) is not None
            if engaged and now >= next_flee_attempt_monotonic:
                from command_handlers.movement import flee

                flee(session)
                next_flee_attempt_monotonic = now + OFFLINE_FLEE_INTERVAL_SECONDS

            while now >= next_hour_tick_monotonic:
                process_game_hour_tick(session)
                save_player_state(session)
                next_hour_tick_monotonic += GAME_TICK_INTERVAL_SECONDS
                session.next_game_tick_monotonic = next_hour_tick_monotonic

                hp_now = session.status.hit_points
                took_damage = hp_now < previous_hit_points
                engaged_after_tick = get_engaged_entity(session) is not None

                if not engaged_after_tick and not took_damage:
                    safe_hours += 1
                else:
                    safe_hours = 0

                previous_hit_points = hp_now

                if safe_hours >= OFFLINE_SAFE_HOURS_TO_DISCONNECT:
                    session.disconnected_by_server = True
                    session.is_connected = False
                    if session.login_room_id.strip():
                        session.player.current_room_id = session.login_room_id.strip()
                    end_combat(session)
                    purge_nonpersistent_items(session, reason="offline_safe_disconnect")
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
        clear_transient_interaction_flags_for_session(session)
        if session.player_state_key.strip():
            save_player_state(session)
        start_offline_character_processing(session)


def reset_session_to_login(session: ClientSession, *, purge_nonpersistent_items_on_logout: bool = False) -> None:
    """Save and deauthenticate a session, returning it to the login screen."""
    normalized_key = session.player_state_key.strip().lower()
    if normalized_key:
        if purge_nonpersistent_items_on_logout:
            purge_nonpersistent_items(session, reason="logout")
        save_player_state(session)
        active_character_sessions.pop(normalized_key, None)
        stop_offline_character_processing(normalized_key)

    session.is_authenticated = False
    session.auth_stage = "awaiting_character_or_start"
    session.authenticated_character_name = ""
    session.player_state_key = ""
    session.player.gender = "unspecified"
    session.pending_character_name = ""
    session.pending_password = ""
    session.pending_gender = ""
    session.following_player_key = ""
    session.following_player_name = ""
    session.watch_player_key = ""
    session.watch_player_name = ""
    session.group_leader_key = ""
    session.group_member_keys.clear()
    session.pending_private_lines = []
    session.lag_until_monotonic = None
    session.pending_death_logout = False
