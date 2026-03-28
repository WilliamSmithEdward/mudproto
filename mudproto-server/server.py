import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from websockets.asyncio.server import ServerConnection
import websockets


MAX_QUEUED_COMMANDS = 5
COMMAND_SCHEDULER_INTERVAL_SECONDS = 0.1


@dataclass
class QueuedCommand:
    command_text: str
    received_at_iso: str


@dataclass
class ClientSession:
    client_id: str
    websocket: ServerConnection
    connected_at: str
    last_message_at: Optional[str] = None
    lag_until_monotonic: Optional[float] = None
    command_queue: list[QueuedCommand] = field(default_factory=list)
    scheduler_task: Optional[asyncio.Task] = None


connected_clients: dict[str, ClientSession] = {}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_response(message_type: str, payload: dict) -> dict:
    return {
        "type": message_type,
        "source": "mudproto-server",
        "timestamp": utc_now_iso(),
        "payload": payload
    }


def build_part(text: str, fg: str = "bright_white", bold: bool = False) -> dict:
    return {
        "text": text,
        "fg": fg,
        "bold": bold
    }


def build_display(parts: list[dict], *, blank_lines_before: int = 1, prompt_after: bool = True) -> dict:
    return build_response("display", {
        "parts": parts,
        "blank_lines_before": blank_lines_before,
        "prompt_after": prompt_after
    })


def display_text(
    text: str,
    *,
    fg: str = "bright_white",
    bold: bool = False,
    blank_lines_before: int = 1,
    prompt_after: bool = True
) -> dict:
    return build_display(
        [build_part(text, fg, bold)],
        blank_lines_before=blank_lines_before,
        prompt_after=prompt_after
    )


def validate_message(message: object) -> str | None:
    required_fields = ["type", "source", "timestamp", "payload"]

    if not isinstance(message, dict):
        return "Message must be a JSON object."

    for field_name in required_fields:
        if field_name not in message:
            return f"Missing required field: {field_name}"

    if not isinstance(message["type"], str):
        return "Field 'type' must be a string."

    if not isinstance(message["source"], str):
        return "Field 'source' must be a string."

    if not isinstance(message["timestamp"], str):
        return "Field 'timestamp' must be a string."

    if not isinstance(message["payload"], dict):
        return "Field 'payload' must be an object."

    return None


def get_connection_count() -> int:
    return len(connected_clients)


def register_client(client_id: str, websocket: ServerConnection) -> ClientSession:
    session = ClientSession(
        client_id=client_id,
        websocket=websocket,
        connected_at=utc_now_iso()
    )
    connected_clients[client_id] = session
    return session


def unregister_client(client_id: str) -> None:
    connected_clients.pop(client_id, None)


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


def parse_command(command_text: str) -> tuple[str, list[str]]:
    normalized = command_text.strip()
    if not normalized:
        return "", []

    parts = normalized.split()
    verb = parts[0].lower()
    args = parts[1:]
    return verb, args


def display_connected(session: ClientSession) -> dict:
    return build_display([
        build_part("Connection established. ", "bright_green", True),
        build_part("Client ID: ", "bright_white"),
        build_part(session.client_id, "bright_yellow")
    ])


def display_hello(name: str) -> dict:
    return build_display([
        build_part("Hello, ", "bright_green"),
        build_part(str(name), "bright_white", True)
    ])


def display_pong() -> dict:
    return display_text("Ping received.", fg="bright_cyan")


def display_whoami(session: ClientSession) -> dict:
    remaining_lag = round(get_remaining_lag_seconds(session), 3)
    queued_count = len(session.command_queue)

    return build_display([
        build_part("Client ID: ", "bright_white"),
        build_part(session.client_id, "bright_yellow"),
        build_part(" | Connected: ", "bright_white"),
        build_part(session.connected_at, "bright_cyan"),
        build_part(" | Last Message: ", "bright_white"),
        build_part(str(session.last_message_at), "bright_magenta"),
        build_part(" | Lag: ", "bright_white"),
        build_part(str(remaining_lag), "bright_yellow", True),
        build_part(" | Queued: ", "bright_white"),
        build_part(str(queued_count), "bright_yellow", True)
    ])


def display_error(message: str) -> dict:
    return build_display([
        build_part("Error: ", "bright_red", True),
        build_part(message, "bright_white")
    ])


def display_system(message: str) -> dict:
    return display_text(message, fg="bright_cyan")


def display_queue_ack(session: ClientSession, command_text: str) -> dict:
    return build_display([
        build_part("Queued: ", "bright_yellow", True),
        build_part(f'"{command_text}"', "bright_white"),
        build_part(" | Remaining lag: ", "bright_white"),
        build_part(str(round(get_remaining_lag_seconds(session), 3)), "bright_yellow", True),
        build_part(" | Queue depth: ", "bright_white"),
        build_part(str(len(session.command_queue)), "bright_magenta", True)
    ])


def display_command_result(
    parts: list[dict],
    *,
    blank_lines_before: int = 1,
    prompt_after: bool = True
) -> dict:
    return build_display(parts, blank_lines_before=blank_lines_before, prompt_after=prompt_after)


def execute_command(session: ClientSession, command_text: str) -> dict:
    verb, args = parse_command(command_text)

    if not verb:
        return display_error("Command text is empty.")

    if verb == "look":
        return display_command_result([
            build_part("You are standing in ", "bright_white"),
            build_part("a prototype room", "bright_green", True),
            build_part(". Exits: ", "bright_white"),
            build_part("none", "bright_yellow", True),
            build_part(".", "bright_white")
        ])

    if verb == "wait":
        return display_command_result([
            build_part("You wait.", "bright_white")
        ])

    if verb == "heavy":
        apply_lag(session, 3.0)
        return display_command_result([
            build_part("You use ", "bright_white"),
            build_part("a heavy skill", "bright_red", True),
            build_part(". Lag applied for ", "bright_white"),
            build_part("3.0", "bright_yellow", True),
            build_part(" seconds.", "bright_white")
        ])

    if verb == "say":
        spoken_text = " ".join(args).strip()
        if not spoken_text:
            return display_error("Usage: say <text>")

        return display_command_result([
            build_part("You say, ", "bright_white"),
            build_part(f'"{spoken_text}"', "bright_magenta", True)
        ])

    return display_error(f"Unknown command: {verb}")


async def process_command_message(message: dict, session: ClientSession) -> dict:
    payload = message["payload"]
    command_text = payload.get("command_text")

    if not isinstance(command_text, str):
        return display_error("Field 'payload.command_text' must be a string.")

    if is_session_lagged(session):
        was_queued, queue_message = enqueue_command(session, command_text)
        if not was_queued:
            return display_error(queue_message)

        return display_queue_ack(session, command_text)

    return execute_command(session, command_text)


def handle_hello(message: dict, session: ClientSession) -> dict:
    payload = message["payload"]
    name = payload.get("name", "unknown")
    return display_hello(str(name))


def handle_ping(message: dict, session: ClientSession) -> dict:
    return display_pong()


def handle_whoami(message: dict, session: ClientSession) -> dict:
    return display_whoami(session)


async def dispatch_message(message: dict, session: ClientSession) -> dict:
    msg_type = message["type"]

    if msg_type == "hello":
        return handle_hello(message, session)

    if msg_type == "ping":
        return handle_ping(message, session)

    if msg_type == "whoami":
        return handle_whoami(message, session)

    if msg_type == "command":
        return await process_command_message(message, session)

    return display_error(f"Unsupported message type: {msg_type}")


async def send_json(websocket: ServerConnection, message: dict) -> None:
    message_text = json.dumps(message)
    await websocket.send(message_text)
    print(f"Sent response: {message}")


async def command_scheduler_loop(session: ClientSession) -> None:
    try:
        while True:
            await asyncio.sleep(COMMAND_SCHEDULER_INTERVAL_SECONDS)

            if session.client_id not in connected_clients:
                break

            if is_session_lagged(session):
                continue

            if not session.command_queue:
                continue

            queued_command = session.command_queue.pop(0)

            queued_notice = display_system(f'Executing queued command: "{queued_command.command_text}"')
            await send_json(session.websocket, queued_notice)

            result = execute_command(session, queued_command.command_text)
            await send_json(session.websocket, result)

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
    session.scheduler_task = asyncio.create_task(command_scheduler_loop(session))

    print(f"Client connected: {session.client_id}")
    print(f"Connected clients: {get_connection_count()}")

    try:
        await send_json(session.websocket, display_connected(session))

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
            await send_json(session.websocket, response)

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