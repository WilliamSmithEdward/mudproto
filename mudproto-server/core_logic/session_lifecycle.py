import asyncio

from models import ClientSession
from player_state_db import save_player_state
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
                from command_handlers.runtime import flee

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


def reset_session_to_login(session: ClientSession) -> None:
    """Save and deauthenticate a session, returning it to the login screen."""
    normalized_key = session.player_state_key.strip().lower()
    if normalized_key:
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
    session.pending_private_lines = []
    session.lag_until_monotonic = None
    session.pending_death_logout = False
