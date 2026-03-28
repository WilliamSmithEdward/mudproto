from display import (
    build_part,
    display_command_result,
    display_error,
    display_hello,
    display_pong,
    display_prompt,
    display_queue_ack,
    display_room,
    display_whoami,
)
from models import ClientSession
from sessions import apply_lag, enqueue_command, is_session_lagged
from world import get_room


DIRECTION_ALIASES = {
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
}


def parse_command(command_text: str) -> tuple[str, list[str]]:
    normalized = command_text.strip()
    if not normalized:
        return "", []

    parts = normalized.split()
    verb = parts[0].lower()
    args = parts[1:]
    return verb, args


def normalize_direction(direction: str) -> str:
    direction = direction.lower().strip()
    return DIRECTION_ALIASES.get(direction, direction)


def try_move(session: ClientSession, direction: str) -> dict:
    current_room = get_room(session.current_room_id)
    if current_room is None:
        return display_error(f"Current room not found: {session.current_room_id}", session)

    normalized_direction = normalize_direction(direction)
    next_room_id = current_room.exits.get(normalized_direction)

    if next_room_id is None:
        return display_error(f"You cannot go {normalized_direction} from here.", session)

    next_room = get_room(next_room_id)
    if next_room is None:
        return display_error(f"Destination room not found: {next_room_id}", session)

    session.current_room_id = next_room.room_id
    return display_room(session, next_room)


def execute_command(session: ClientSession, command_text: str) -> dict:
    verb, args = parse_command(command_text)

    if not verb:
        return display_prompt(session)

    if verb == "look":
        room = get_room(session.current_room_id)
        if room is None:
            return display_error(f"Current room not found: {session.current_room_id}", session)

        return display_room(session, room)

    if verb in {"north", "south", "east", "west", "up", "down", "n", "s", "e", "w", "u", "d"}:
        return try_move(session, verb)

    if verb == "go":
        if not args:
            return display_error("Usage: go <direction>", session)

        return try_move(session, args[0])

    if verb == "wait":
        return display_command_result(session, [
            build_part("You wait.", "bright_white")
        ])

    if verb == "heavy":
        apply_lag(session, 3.0)
        return display_command_result(session, [
            build_part("You use ", "bright_white"),
            build_part("a heavy skill", "bright_red", True),
            build_part(". Lag applied for ", "bright_white"),
            build_part("3.0", "bright_yellow", True),
            build_part(" seconds.", "bright_white")
        ])

    if verb == "say":
        spoken_text = " ".join(args).strip()
        if not spoken_text:
            return display_error("Usage: say <text>", session)

        return display_command_result(session, [
            build_part("You say, ", "bright_white"),
            build_part(f'"{spoken_text}"', "bright_magenta", True)
        ])

    return display_error(f"Unknown command: {verb}", session)


async def process_input_message(message: dict, session: ClientSession) -> dict:
    payload = message["payload"]
    input_text = payload.get("text")

    if input_text is None:
        return display_prompt(session)

    if not isinstance(input_text, str):
        return display_error("Field 'payload.text' must be a string.", session)

    input_text = input_text.strip()
    if not input_text:
        return display_prompt(session)

    if input_text.startswith("/"):
        command_line = input_text[1:].strip()
        verb, args = parse_command(command_line)

        if not verb:
            return display_prompt(session)

        if verb == "hello":
            name = " ".join(args).strip() or "unknown"
            return display_hello(name, session)

        if verb == "ping":
            return display_pong(session)

        if verb == "whoami":
            return display_whoami(session)

        return display_error(f"Unknown slash command: /{verb}", session)

    if is_session_lagged(session):
        was_queued, queue_message = enqueue_command(session, input_text)
        if not was_queued:
            return display_error(queue_message, session)

        return display_queue_ack(session, input_text)

    return execute_command(session, input_text)


async def dispatch_message(message: dict, session: ClientSession) -> dict:
    msg_type = message["type"]

    if msg_type == "input":
        return await process_input_message(message, session)

    return display_error(f"Unsupported message type: {msg_type}")