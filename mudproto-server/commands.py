from display import (
    build_part,
    display_command_result,
    display_error,
    display_hello,
    display_pong,
    display_queue_ack,
    display_room,
    display_whoami,
)
from models import ClientSession
from sessions import apply_lag, enqueue_command, is_session_lagged
from world import get_room


def parse_command(command_text: str) -> tuple[str, list[str]]:
    normalized = command_text.strip()
    if not normalized:
        return "", []

    parts = normalized.split()
    verb = parts[0].lower()
    args = parts[1:]
    return verb, args


def execute_command(session: ClientSession, command_text: str) -> dict:
    verb, args = parse_command(command_text)

    if not verb:
        return display_error("Command text is empty.")

    if verb == "look":
        room = get_room(session.current_room_id)
        if room is None:
            return display_error(f"Current room not found: {session.current_room_id}")

        return display_room(room)

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


async def process_input_message(message: dict, session: ClientSession) -> dict:
    payload = message["payload"]
    input_text = payload.get("text")

    if not isinstance(input_text, str):
        return display_error("Field 'payload.text' must be a string.")

    input_text = input_text.strip()
    if not input_text:
        return display_error("Input text is empty.")

    if input_text.startswith("/"):
        command_line = input_text[1:].strip()
        verb, args = parse_command(command_line)

        if not verb:
            return display_error("Slash command is empty.")

        if verb == "hello":
            name = " ".join(args).strip() or "unknown"
            return display_hello(name)

        if verb == "ping":
            return display_pong()

        if verb == "whoami":
            return display_whoami(session)

        return display_error(f"Unknown slash command: /{verb}")

    if is_session_lagged(session):
        was_queued, queue_message = enqueue_command(session, input_text)
        if not was_queued:
            return display_error(queue_message)

        return display_queue_ack(session, input_text)

    return execute_command(session, input_text)


async def dispatch_message(message: dict, session: ClientSession) -> dict:
    msg_type = message["type"]

    if msg_type == "input":
        return await process_input_message(message, session)

    return display_error(f"Unsupported message type: {msg_type}")