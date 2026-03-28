import asyncio

from models import ClientSession, QueuedCommand
from protocol import utc_now_iso


MAX_QUEUED_COMMANDS = 5

connected_clients: dict[str, ClientSession] = {}


def get_connection_count() -> int:
    return len(connected_clients)


def register_client(client_id: str, websocket) -> ClientSession:
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