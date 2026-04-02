import asyncio
import json
import re
import uuid
from typing import TypeAlias

from grammar import third_personize_text
from websockets.asyncio.server import ServerConnection
import websockets

from battle_round_ticks import process_non_combat_support_round
from combat import get_engaged_entities, initialize_session_entities, resolve_combat_round, tick_out_of_combat_cooldowns
from commands import dispatch_message, execute_command, initial_auth_prompt, login_prompt, parse_command
from display import (
    build_display,
    build_part,
    build_prompt_parts,
    display_connected,
    display_error,
    display_force_prompt,
    display_prompt,
    display_room,
)
from models import ClientSession
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
    reset_session_to_login,
    touch_session,
)
from game_hour_ticks import process_game_hour_tick
from world import get_room

RoomRoundResult: TypeAlias = tuple[ClientSession, dict]

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
def _build_room_broadcast_messages(origin_session, outbound: dict | list[dict]) -> list[dict]:
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
                        part["text"] = third_personize_text(original_text, actor_name)
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


def _extract_display_lines(message: dict | None) -> list[str]:
    if not isinstance(message, dict):
        return []
    if message.get("type") != "display":
        return []

    payload = message.get("payload")
    if not isinstance(payload, dict):
        return []

    parts = payload.get("parts")
    if not isinstance(parts, list):
        return []

    text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
    lines = text.split("\n")

    while lines and not lines[0].strip():
        lines.pop(0)

    while lines and not lines[-1].strip():
        lines.pop()

    return [line.strip() if line.strip() else "" for line in lines]


def _split_actor_round_lines(lines: list[str], actor_prefix: str) -> tuple[list[str], list[str]]:
    player_lines: list[str] = []
    retaliation_lines: list[str] = []
    in_retaliation = False
    normalized_prefix = actor_prefix.strip().lower()

    for line in lines:
        if not line.strip():
            if in_retaliation:
                retaliation_lines.append("")
            else:
                player_lines.append("")
            continue

        normalized_line = line.strip().lower()
        is_actor_line = normalized_line.startswith(normalized_prefix)
        if not in_retaliation and is_actor_line:
            player_lines.append(line)
            continue

        in_retaliation = True
        retaliation_lines.append(line)

    return player_lines, retaliation_lines


def _build_unified_room_round_display(
    recipient_session: ClientSession,
    room_round_results: list[RoomRoundResult],
) -> dict | None:
    player_phase_lines: list[str] = []
    retaliation_phase_lines: list[str] = []

    for actor_session, actor_result in room_round_results:
        actor_name = actor_session.authenticated_character_name or "Someone"
        if recipient_session.client_id == actor_session.client_id:
            recipient_message = actor_result
            actor_prefix = "you "
        else:
            observer_messages = _build_room_broadcast_messages(actor_session, actor_result)
            if not observer_messages:
                continue
            recipient_message = observer_messages[0]
            actor_prefix = f"{actor_name.lower()} "

        lines = _extract_display_lines(recipient_message)
        if not lines:
            continue

        actor_lines, retaliation_lines = _split_actor_round_lines(lines, actor_prefix)
        player_phase_lines.extend(actor_lines)
        retaliation_phase_lines.extend(retaliation_lines)

    merged_lines = player_phase_lines + retaliation_phase_lines
    if not merged_lines:
        return None

    parts: list[dict] = []
    for index, line in enumerate(merged_lines):
        if index > 0:
            parts.append(build_part("\n"))
        parts.append(build_part(line))

    return build_display(parts, blank_lines_before=0, starts_on_new_line=True)


async def _send_room_broadcast(origin_session, broadcast_messages: list[dict], *, prompt_observers: bool = True) -> None:
    if not broadcast_messages:
        return

    peers = _iter_room_peers(origin_session)
    for peer in peers:
        peer_messages = json.loads(json.dumps(broadcast_messages))
        if prompt_observers:
            for message in peer_messages:
                if isinstance(message, dict) and message.get("type") == "display":
                    payload = message.get("payload")
                    if isinstance(payload, dict):
                        payload["prompt_after"] = True
                        payload["prompt_parts"] = build_prompt_parts(peer)
        await send_outbound(peer.websocket, peer_messages)


async def _broadcast_battle_outbound_to_room(origin_session, outbound: dict | list[dict]) -> None:
    broadcast_messages = _build_room_broadcast_messages(origin_session, outbound)
    await _send_room_broadcast(origin_session, broadcast_messages, prompt_observers=True)


async def _broadcast_non_combat_outbound_to_room(origin_session, outbound: dict | list[dict]) -> None:
    broadcast_messages = _build_room_broadcast_messages(origin_session, outbound)
    await _send_room_broadcast(origin_session, broadcast_messages, prompt_observers=True)


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
                    await _broadcast_non_combat_outbound_to_room(session, result)
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
            await send_outbound(session.websocket, response)

            if session.pending_death_logout:
                reset_session_to_login(session)
                await send_outbound(session.websocket, login_prompt(session))
                continue

            if message.get("type") == "input":
                payload = message.get("payload", {})
                input_text = payload.get("text") if isinstance(payload, dict) else None
                if isinstance(input_text, str) and session.is_authenticated and _looks_like_skill_spell_or_item_action(input_text, response):
                    await _broadcast_non_combat_outbound_to_room(session, response)

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