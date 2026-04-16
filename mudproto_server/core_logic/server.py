import asyncio
import json
import logging
import ssl
import uuid

from websockets.asyncio.server import ServerConnection
import websockets

from commands import dispatch_message
from display_feedback import display_connected, display_error
from display_prompts import initial_auth_prompt, login_prompt
from protocol import validate_message
from server_broadcasts import (
    _broadcast_non_combat_outbound_to_room,
    _inject_private_lines_into_outbound,
    _looks_like_skill_spell_or_item_action,
)
from server_loops import (
    combat_round_loop,
    command_scheduler_loop,
    game_tick_loop,
    get_next_game_tick_monotonic,
)
from server_movement import _handle_movement_side_effects
from server_transport import send_json, send_outbound
from settings import (
    GAME_TICK_INTERVAL_SECONDS,
    SERVER_HOST,
    SERVER_PORT,
    SERVER_TLS_CERTFILE,
    SERVER_TLS_ENABLED,
    SERVER_TLS_KEYFILE,
)
from session_lifecycle import handle_client_disconnect, reset_session_to_login
from session_registry import get_connection_count, register_client
from session_timing import touch_session
from world_population import initialize_session_entities, initialize_shared_world_state


WEBSOCKET_SERVER_LOGGER_NAME = "mudproto.websocket"


def _is_expected_handshake_disconnect(exc: BaseException | None) -> bool:
    pending = [exc]
    seen: set[int] = set()

    while pending:
        current = pending.pop()
        if current is None:
            continue
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)

        if isinstance(current, EOFError):
            return True
        if isinstance(current, websockets.exceptions.InvalidMessage) and "did not receive a valid HTTP request" in str(current):
            return True

        pending.append(current.__cause__)
        pending.append(current.__context__)

    return False


class _SuppressExpectedHandshakeNoise(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.getMessage() != "opening handshake failed":
            return True

        exc_info = record.exc_info
        exception = exc_info[1] if exc_info is not None and len(exc_info) >= 2 else None
        if isinstance(exception, BaseException) and _is_expected_handshake_disconnect(exception):
            record.msg = "WebSocket handshake closed before a valid request was received."
            record.args = ()
            record.exc_info = None

        return True


def _build_websocket_logger() -> logging.Logger:
    logger = logging.getLogger(WEBSOCKET_SERVER_LOGGER_NAME)
    if not any(isinstance(existing_filter, _SuppressExpectedHandshakeNoise) for existing_filter in logger.filters):
        logger.addFilter(_SuppressExpectedHandshakeNoise())
    return logger


def _build_server_ssl_context() -> ssl.SSLContext | None:
    if not SERVER_TLS_ENABLED:
        return None

    if SERVER_TLS_CERTFILE is None or SERVER_TLS_KEYFILE is None:
        raise ValueError("TLS is enabled, but tls_certfile and tls_keyfile must both be configured.")
    if not SERVER_TLS_CERTFILE.exists():
        raise FileNotFoundError(f"TLS certificate file not found: {SERVER_TLS_CERTFILE}")
    if not SERVER_TLS_KEYFILE.exists():
        raise FileNotFoundError(f"TLS key file not found: {SERVER_TLS_KEYFILE}")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(SERVER_TLS_CERTFILE), keyfile=str(SERVER_TLS_KEYFILE))
    return context


async def handle_connection(websocket: ServerConnection) -> None:
    client_id = str(uuid.uuid4())
    session = register_client(client_id, websocket)
    session.next_game_tick_monotonic = get_next_game_tick_monotonic()
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

            if session.disconnected_by_server and not session.is_connected:
                try:
                    await session.websocket.close(code=4003, reason="Disconnected by server")
                except Exception:
                    pass
                break

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
    initialize_shared_world_state()
    tick_task = asyncio.create_task(game_tick_loop())
    combat_task = asyncio.create_task(combat_round_loop())

    ssl_context = _build_server_ssl_context()
    scheme = "wss" if ssl_context is not None else "ws"

    websocket_logger = _build_websocket_logger()

    try:
        async with websockets.serve(
            handle_connection,
            SERVER_HOST,
            SERVER_PORT,
            ssl=ssl_context,
            logger=websocket_logger,
        ):
            print(f"Server listening on {scheme}://{SERVER_HOST}:{SERVER_PORT}")
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