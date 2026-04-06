import asyncio
import json
import uuid
from typing import TypeAlias

from websockets.asyncio.server import ServerConnection
import websockets

from battle_round_ticks import process_non_combat_support_round
from combat import (
    get_engaged_entities,
    maybe_auto_engage_current_room,
    process_entity_game_hour_tick,
    resolve_combat_round,
    tick_out_of_combat_cooldowns,
)
from command_handlers.auth import initial_auth_prompt, login_prompt
from command_handlers.registry import dispatch_command
from commands import dispatch_message
from display_feedback import display_connected, display_error, display_force_prompt, display_prompt
from game_hour_ticks import process_game_hour_tick
from models import ClientSession
from player_state_db import save_player_state
from protocol import validate_message
from server_broadcasts import (
    _build_unified_room_round_display,
    _broadcast_non_combat_outbound_to_room,
    _inject_private_lines_into_outbound,
    _looks_like_skill_spell_or_item_action,
)
from server_movement import _handle_movement_side_effects
from settings import (
    COMBAT_ROUND_INTERVAL_SECONDS,
    COMMAND_SCHEDULER_INTERVAL_SECONDS,
    GAME_TICK_INTERVAL_SECONDS,
    SERVER_HOST,
    SERVER_PORT,
)
from session_lifecycle import (
    handle_client_disconnect,
    reset_session_to_login,
)
from session_registry import (
    active_character_sessions,
    connected_clients,
    get_connection_count,
    register_client,
    shared_world_entities,
)
from session_timing import is_session_lagged, touch_session
from world_population import initialize_session_entities, repopulate_game_hour_zones

RoomRoundResult: TypeAlias = tuple[ClientSession, dict]

next_game_tick_monotonic: float | None = None
next_combat_round_monotonic: float | None = None


async def send_json(websocket: ServerConnection, message: dict) -> bool:
    message_text = json.dumps(message)
    try:
        await websocket.send(message_text)
    except websockets.ConnectionClosed:
        return False

    print(f"Sent response: {message}")
    return True


async def send_outbound(
    websocket: ServerConnection,
    outbound: dict | list[dict],
) -> bool:
    delivered = True
    if isinstance(outbound, list):
        for message in outbound:
            delivered = await send_json(websocket, message) and delivered
    else:
        delivered = await send_json(websocket, outbound)
    return delivered


async def command_scheduler_loop(session) -> None:
    try:
        while True:
            await asyncio.sleep(COMMAND_SCHEDULER_INTERVAL_SECONDS)

            if session.client_id not in connected_clients:
                break

            now = asyncio.get_running_loop().time()
            while session.next_game_tick_monotonic is not None and now >= session.next_game_tick_monotonic:
                process_game_hour_tick(session)
                if session.is_authenticated:
                    save_player_state(session)
                session.next_game_tick_monotonic += GAME_TICK_INTERVAL_SECONDS

            process_non_combat_support_round(session)

            # Re-attempt auto-aggro periodically so hostile NPCs can engage
            # without requiring player movement or explicit room refresh.
            if session.is_authenticated and not session.combat.engaged_entity_ids:
                maybe_auto_engage_current_room(session)

            if is_session_lagged(session):
                continue

            if session.command_queue:
                queued_command = session.command_queue.pop(0)

                result = dispatch_command(session, queued_command.command_text)
                await _handle_movement_side_effects(session, result, send_outbound)
                result = _inject_private_lines_into_outbound(session, result)
                await send_outbound(session.websocket, result)
                if _looks_like_skill_spell_or_item_action(queued_command.command_text, result):
                    await _broadcast_non_combat_outbound_to_room(session, result, send_outbound)
                continue

            if session.prompt_pending_after_lag:
                session.prompt_pending_after_lag = False
                await send_json(session.websocket, display_prompt(session))

    except asyncio.CancelledError:
        raise
    except Exception as ex:
        error_message = display_error(f"Scheduler failure: {str(ex)}")

        try:
            await send_json(session.websocket, error_message)
        except Exception:
            pass


async def game_tick_loop() -> None:
    global next_game_tick_monotonic

    try:
        next_game_tick_monotonic = asyncio.get_running_loop().time() + GAME_TICK_INTERVAL_SECONDS

        while True:
            sleep_seconds = max(0.0, next_game_tick_monotonic - asyncio.get_running_loop().time())
            await asyncio.sleep(sleep_seconds)

            next_game_tick_monotonic += GAME_TICK_INTERVAL_SECONDS

            for entity in list(shared_world_entities.values()):
                if not getattr(entity, "is_alive", False):
                    continue
                process_entity_game_hour_tick(entity)

            repopulate_game_hour_zones()

    except asyncio.CancelledError:
        raise


async def combat_round_loop() -> None:
    global next_combat_round_monotonic

    try:
        next_combat_round_monotonic = asyncio.get_running_loop().time() + COMBAT_ROUND_INTERVAL_SECONDS

        while True:
            sleep_seconds = max(0.0, next_combat_round_monotonic - asyncio.get_running_loop().time())
            await asyncio.sleep(sleep_seconds)
            next_combat_round_monotonic += COMBAT_ROUND_INTERVAL_SECONDS

            combat_sessions: list[ClientSession] = []
            seen_sessions: set[str] = set()

            for session in active_character_sessions.values():
                session_key = session.player_state_key.strip().lower() or session.client_id
                if not session_key or session_key in seen_sessions:
                    continue
                seen_sessions.add(session_key)

                if session.disconnected_by_server or not session.is_authenticated:
                    continue
                if not session.combat.engaged_entity_ids:
                    continue
                combat_sessions.append(session)

            # Fallback: include authenticated connected sessions not yet in active character map.
            for session in connected_clients.values():
                session_key = session.player_state_key.strip().lower() or session.client_id
                if not session_key or session_key in seen_sessions:
                    continue
                seen_sessions.add(session_key)

                if not session.is_connected or session.disconnected_by_server or not session.is_authenticated:
                    continue
                if not session.combat.engaged_entity_ids:
                    continue
                combat_sessions.append(session)

            combat_rooms: dict[str, list[ClientSession]] = {}
            for session in combat_sessions:
                room_id = session.player.current_room_id
                if not room_id:
                    continue
                combat_rooms.setdefault(room_id, []).append(session)

            # Tick skill cooldowns for authenticated sessions not currently in combat.
            combat_session_ids = {s.client_id for s in combat_sessions}
            for session in list(connected_clients.values()):
                if session.client_id in combat_session_ids:
                    continue
                if not session.is_authenticated or session.disconnected_by_server:
                    continue
                tick_out_of_combat_cooldowns(session)

            for room_id, room_sessions in combat_rooms.items():
                round_results: list[RoomRoundResult] = []
                room_sessions.sort(key=lambda s: (s.authenticated_character_name or "", s.client_id))

                # One active target session per NPC/entity each room round.
                entity_active_target_session: dict[str, str] = {}
                for actor_session in room_sessions:
                    engaged_entities = get_engaged_entities(actor_session)
                    if not engaged_entities:
                        continue
                    for engaged_entity in engaged_entities:
                        entity_active_target_session.setdefault(engaged_entity.entity_id, actor_session.client_id)

                for actor_session in room_sessions:
                    allowed_entity_retaliation_ids = {
                        entity_id
                        for entity_id, target_session_id in entity_active_target_session.items()
                        if target_session_id == actor_session.client_id
                    }

                    combat_result = resolve_combat_round(
                        actor_session,
                        allowed_entity_retaliation_ids=allowed_entity_retaliation_ids,
                    )
                    if combat_result is not None:
                        round_results.append((actor_session, combat_result))

                if not round_results:
                    continue

                room_recipients = [
                    session
                    for session in connected_clients.values()
                    if session.is_connected
                    and not session.disconnected_by_server
                    and session.is_authenticated
                    and session.player.current_room_id == room_id
                ]

                for recipient in room_recipients:
                    # Skip the force_prompt for players about to logout after death
                    skip_prompt = any(
                        actor_session == recipient and actor_session.pending_death_logout
                        for actor_session, _ in round_results
                    )
                    unified_display = _build_unified_room_round_display(recipient, round_results)
                    if unified_display is None:
                        continue
                    outbounds = [unified_display]
                    if not skip_prompt:
                        outbounds.append(display_force_prompt(recipient))
                    outbounds = _inject_private_lines_into_outbound(recipient, outbounds)
                    await send_outbound(recipient.websocket, outbounds)

                for actor_session, _ in round_results:
                    if not actor_session.pending_death_logout:
                        continue
                    reset_session_to_login(actor_session)
                    if actor_session.is_connected:
                        await send_outbound(actor_session.websocket, initial_auth_prompt(actor_session))

    except asyncio.CancelledError:
        raise


async def handle_connection(websocket: ServerConnection) -> None:
    client_id = str(uuid.uuid4())
    session = register_client(client_id, websocket)
    session.next_game_tick_monotonic = next_game_tick_monotonic
    if session.next_game_tick_monotonic is None:
        session.next_game_tick_monotonic = asyncio.get_running_loop().time() + GAME_TICK_INTERVAL_SECONDS
    initialize_session_entities(session)
    session.scheduler_task = asyncio.create_task(command_scheduler_loop(session))

    print(f"Client connected: {session.client_id}")
    print(f"Connected clients: {get_connection_count()}")

    try:
        await send_json(session.websocket, display_connected(session))
        await send_json(session.websocket, initial_auth_prompt(session))

        async for message_text in session.websocket:
            touch_session(session)

            print(f"Raw message from {session.client_id}: {message_text}")

            try:
                message = json.loads(message_text)
            except json.JSONDecodeError as ex:
                response = display_error(f"Invalid JSON. {str(ex)}")
                await send_json(session.websocket, response)
                continue

            print(f"Parsed message from {session.client_id}: {message}")

            error_message = validate_message(message)
            if error_message is not None:
                response = display_error(error_message)
                await send_json(session.websocket, response)
                continue

            response = await dispatch_message(message, session)
            await _handle_movement_side_effects(session, response, send_outbound)
            response = _inject_private_lines_into_outbound(session, response)
            await send_outbound(session.websocket, response)

            if session.pending_death_logout:
                reset_session_to_login(session)
                await send_outbound(session.websocket, login_prompt(session))
                continue

            if message.get("type") == "input":
                payload = message.get("payload", {})
                input_text = payload.get("text") if isinstance(payload, dict) else None
                if isinstance(input_text, str) and session.is_authenticated and _looks_like_skill_spell_or_item_action(input_text, response):
                    await _broadcast_non_combat_outbound_to_room(session, response, send_outbound)
    except websockets.ConnectionClosed:
        pass
    finally:
        if session.scheduler_task is not None:
            session.scheduler_task.cancel()
            try:
                await session.scheduler_task
            except asyncio.CancelledError:
                pass

        handle_client_disconnect(session)
        print(f"Client disconnected: {session.client_id}")
        print(f"Connected clients: {get_connection_count()}")


async def main():
    tick_task = asyncio.create_task(game_tick_loop())
    combat_task = asyncio.create_task(combat_round_loop())

    try:
        async with websockets.serve(handle_connection, SERVER_HOST, SERVER_PORT):
            print(f"Server listening on ws://{SERVER_HOST}:{SERVER_PORT}")
            await asyncio.Future()
    finally:
        combat_task.cancel()
        try:
            await combat_task
        except asyncio.CancelledError:
            pass

        tick_task.cancel()
        try:
            await tick_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())