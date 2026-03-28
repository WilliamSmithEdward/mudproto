import asyncio
import json
import uuid

from websockets.asyncio.server import ServerConnection
import websockets

from combat import initialize_session_entities, resolve_combat_round
from commands import dispatch_message, execute_command
from display import (
    display_connected,
    display_error,
    display_force_prompt,
    display_prompt,
    display_room,
)
from protocol import validate_message
from sessions import (
    connected_clients,
    get_connection_count,
    is_session_lagged,
    register_client,
    touch_session,
    unregister_client,
)
from world import get_room


COMMAND_SCHEDULER_INTERVAL_SECONDS = 0.1


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

            combat_result = None
            if session.next_combat_round_monotonic is not None:
                now = asyncio.get_running_loop().time()
                if now >= session.next_combat_round_monotonic:
                    combat_result = resolve_combat_round(session)

            if combat_result is not None:
                await send_outbound(
                    session.websocket,
                    [combat_result, display_force_prompt(session)],
                )
                continue

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


async def handle_connection(websocket: ServerConnection) -> None:
    client_id = str(uuid.uuid4())
    session = register_client(client_id, websocket)
    initialize_session_entities(session)
    session.scheduler_task = asyncio.create_task(command_scheduler_loop(session))

    print(f"Client connected: {session.client_id}")
    print(f"Connected clients: {get_connection_count()}")

    try:
        await send_json(session.websocket, display_connected(session))

        starting_room = get_room(session.player.current_room_id)
        if starting_room is not None:
            await send_json(session.websocket, display_room(session, starting_room))

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

        unregister_client(session.client_id)
        print(f"Client disconnected: {session.client_id}")
        print(f"Connected clients: {get_connection_count()}")


async def main():
    async with websockets.serve(handle_connection, "localhost", 8765):
        print("Server listening on ws://localhost:8765")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())