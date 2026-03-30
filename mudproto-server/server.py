import asyncio
import json
import uuid

from websockets.asyncio.server import ServerConnection
import websockets

from battle_round_ticks import process_non_combat_support_round
from combat import initialize_session_entities, resolve_combat_round
from commands import dispatch_message, execute_command, initial_auth_prompt
from display import (
    display_connected,
    display_error,
    display_force_prompt,
    display_prompt,
    display_room,
)
from player_state_db import save_player_state
from protocol import validate_message
from settings import (
    COMMAND_SCHEDULER_INTERVAL_SECONDS,
    GAME_TICK_INTERVAL_SECONDS,
    SERVER_HOST,
    SERVER_PORT,
)
from sessions import (
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

            combat_result = None
            if session.combat.next_round_monotonic is not None:
                if now >= session.combat.next_round_monotonic:
                    combat_result = resolve_combat_round(session)

            if combat_result is not None:
                await send_outbound(
                    session.websocket,
                    [combat_result, display_force_prompt(session)],
                )
                continue

            process_non_combat_support_round(session)

            if is_session_lagged(session):
                continue

            if session.command_queue:
                queued_command = session.command_queue.pop(0)

                result = execute_command(session, queued_command.command_text)
                await send_outbound(session.websocket, result)
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

    try:
        async with websockets.serve(handle_connection, SERVER_HOST, SERVER_PORT):
            print(f"Server listening on ws://{SERVER_HOST}:{SERVER_PORT}")
            await asyncio.Future()
    finally:
        tick_task.cancel()
        try:
            await tick_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())