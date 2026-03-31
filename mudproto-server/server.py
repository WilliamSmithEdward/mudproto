import asyncio
import json
import re
import uuid

from websockets.asyncio.server import ServerConnection
import websockets

from battle_round_ticks import process_non_combat_support_round
from combat import initialize_session_entities, resolve_combat_round
from commands import dispatch_message, execute_command, initial_auth_prompt, parse_command
from display import (
    build_prompt_parts,
    display_connected,
    display_error,
    display_force_prompt,
    display_prompt,
    display_room,
)
from player_state_db import save_player_state
from protocol import validate_message
from settings import (
    COMBAT_ROUND_INTERVAL_SECONDS,
    COMMAND_SCHEDULER_INTERVAL_SECONDS,
    GAME_TICK_INTERVAL_SECONDS,
    SERVER_HOST,
    SERVER_PORT,
)
from sessions import (
    active_character_sessions,
    connected_clients,
    get_connection_count,
    handle_client_disconnect,
    is_session_lagged,
    register_client,
    touch_session,
)
from game_hour_ticks import process_game_hour_tick
from world import get_room
next_game_tick_monotonic: float | None = None
next_combat_round_monotonic: float | None = None


def _iter_room_peers(origin_session):
    if not origin_session.is_authenticated:
        return []

    room_id = origin_session.player.current_room_id
    peers = []
    for session in connected_clients.values():
        if session.client_id == origin_session.client_id:
            continue
        if not session.is_connected or session.disconnected_by_server or not session.is_authenticated:
            continue
        if session.player.current_room_id != room_id:
            continue
        peers.append(session)
    return peers


def _third_personize_text(text: str, actor_name: str) -> str:
    if not text:
        return text

    possessive = f"{actor_name}'" if actor_name.endswith("s") else f"{actor_name}'s"
    rewritten = text
    rewritten = re.sub(r"\byou are\b", f"{actor_name} is", rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\byou were\b", f"{actor_name} was", rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\byourself\b", "themselves", rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\byour\b", possessive, rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\byou\b", actor_name, rewritten, flags=re.IGNORECASE)
    return rewritten


def _extract_room_broadcast_messages(origin_session, outbound: dict | list[dict]) -> list[dict]:
    messages = outbound if isinstance(outbound, list) else [outbound]
    broadcast_messages: list[dict] = []
    actor_name = origin_session.authenticated_character_name or "Someone"

    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("type") != "display":
            continue

        payload = message.get("payload")
        if not isinstance(payload, dict):
            continue

        parts = payload.get("parts")
        if not isinstance(parts, list) or not parts:
            continue

        from display import build_prompt_parts
        copied_message = json.loads(json.dumps(message))
        copied_payload = copied_message.get("payload")
        if isinstance(copied_payload, dict):
            observer_parts = copied_payload.get("room_broadcast_parts")
            if isinstance(observer_parts, list) and observer_parts:
                copied_payload["parts"] = observer_parts
            else:
                copied_parts = copied_payload.get("parts")
                if isinstance(copied_parts, list):
                    for part in copied_parts:
                        if not isinstance(part, dict):
                            continue
                        original_text = str(part.get("text", ""))
                        part["text"] = _third_personize_text(original_text, actor_name)
            copied_payload["starts_on_new_line"] = True
            copied_payload["blank_lines_before"] = 2
        broadcast_messages.append(copied_message)

    return broadcast_messages


def _looks_like_skill_spell_or_item_action(command_text: str, outbound: dict | list[dict]) -> bool:
    messages = outbound if isinstance(outbound, list) else [outbound]
    for message in messages:
        if not isinstance(message, dict):
            continue
        payload = message.get("payload")
        if not isinstance(payload, dict):
            continue
        parts = payload.get("parts")
        if not isinstance(parts, list):
            continue
        text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()
        if text.startswith("Error:"):
            return False

    verb, _ = parse_command(command_text)
    if verb in {
        "attack", "ki", "kil", "kill", "disengage", "flee",
        "cast", "c", "ca", "cas", "use", "skill", "sk", "ski", "skil", "skl",
    }:
        return True

    for message in messages:
        if not isinstance(message, dict):
            continue
        payload = message.get("payload")
        if not isinstance(payload, dict):
            continue
        parts = payload.get("parts")
        if not isinstance(parts, list):
            continue
        text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip().lower()
        if text.startswith("you cast ") or text.startswith("you use "):
            return True

    return False


async def _broadcast_outbound_to_room(origin_session, outbound: dict | list[dict]) -> None:
    broadcast_messages = _extract_room_broadcast_messages(origin_session, outbound)
    if not broadcast_messages:
        return

    peers = _iter_room_peers(origin_session)
    for peer in peers:
        peer_messages = json.loads(json.dumps(broadcast_messages))
        for message in peer_messages:
            if isinstance(message, dict) and message.get("type") == "display":
                payload = message.get("payload")
                if isinstance(payload, dict):
                    payload["prompt_after"] = True
                    payload["prompt_parts"] = build_prompt_parts(peer)
        await send_outbound(peer.websocket, peer_messages)


async def send_json(websocket: ServerConnection, message: dict) -> None:
    message_text = json.dumps(message)
    await websocket.send(message_text)
    print(f"Sent response: {message}")


async def send_outbound(
    websocket: ServerConnection,
    outbound: dict | list[dict],
) -> None:
    if isinstance(outbound, list):
        for message in outbound:
            await send_json(websocket, message)
    else:
        await send_json(websocket, outbound)


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

            if is_session_lagged(session):
                continue

            if session.command_queue:
                queued_command = session.command_queue.pop(0)

                result = execute_command(session, queued_command.command_text)
                await send_outbound(session.websocket, result)
                if _looks_like_skill_spell_or_item_action(queued_command.command_text, result):
                    await _broadcast_outbound_to_room(session, result)
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

            combat_sessions: list = []
            seen_sessions: set[str] = set()

            for session in active_character_sessions.values():
                session_key = session.player_state_key.strip().lower() or session.client_id
                if not session_key or session_key in seen_sessions:
                    continue
                seen_sessions.add(session_key)

                if session.disconnected_by_server or not session.is_authenticated:
                    continue
                if session.combat.engaged_entity_id is None:
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
                if session.combat.engaged_entity_id is None:
                    continue
                combat_sessions.append(session)

            for session in combat_sessions:
                combat_result = resolve_combat_round(session)
                if combat_result is None:
                    continue

                if session.is_connected:
                    await send_outbound(
                        session.websocket,
                        [combat_result, display_force_prompt(session)],
                    )
                    await _broadcast_outbound_to_room(session, combat_result)

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
            await send_outbound(session.websocket, response)

            if message.get("type") == "input":
                payload = message.get("payload", {})
                input_text = payload.get("text") if isinstance(payload, dict) else None
                if isinstance(input_text, str) and session.is_authenticated and _looks_like_skill_spell_or_item_action(input_text, response):
                    await _broadcast_outbound_to_room(session, response)

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