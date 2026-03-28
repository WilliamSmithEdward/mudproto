from combat import begin_attack, disengage, spawn_dummy
from display import (
    build_part,
    display_command_result,
    display_error,
    display_hello,
    display_pong,
    display_prompt,
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
    "u": "up",
    "d": "down"
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
    current_room = get_room(session.player.current_room_id)
    if current_room is None:
        return display_error(f"Current room not found: {session.player.current_room_id}", session)

    normalized_direction = normalize_direction(direction)
    next_room_id = current_room.exits.get(normalized_direction)

    if next_room_id is None:
        return display_error(f"You cannot go {normalized_direction} from here.", session)

    next_room = get_room(next_room_id)
    if next_room is None:
        return display_error(f"Destination room not found: {next_room_id}", session)

    session.player.current_room_id = next_room.room_id
    session.engaged_entity_id = None
    session.next_combat_round_monotonic = None
    return display_room(session, next_room)


def try_adjust_stat(session: ClientSession, args: list[str], attribute_name: str, label: str, allow_negative: bool = False) -> dict:
    if not args:
        return display_error(f"Usage: {label.lower()} <amount>", session)

    try:
        amount = int(args[0])
    except ValueError:
        return display_error(f"{label} amount must be an integer.", session)

    if not allow_negative and amount < 0:
        return display_error(f"{label} amount must be zero or greater.", session)

    current_value = getattr(session.player, attribute_name)
    new_value = current_value + amount
    if new_value < 0:
        new_value = 0
    setattr(session.player, attribute_name, new_value)

    sign = "+" if amount >= 0 else ""
    return display_command_result(session, [
        build_part(f"{label}: ", "bright_white"),
        build_part(str(current_value), "bright_yellow", True),
        build_part(" -> ", "bright_white"),
        build_part(str(new_value), "bright_green", True),
        build_part(" (", "bright_white"),
        build_part(f"{sign}{amount}", "bright_cyan", True),
        build_part(")", "bright_white"),
    ])


def execute_command(session: ClientSession, command_text: str) -> dict:
    verb, args = parse_command(command_text)

    if not verb:
        return display_prompt(session)

    if verb == "spawn":
        target_name = " ".join(args).strip().lower()
        if target_name != "dummy":
            return display_error("Usage: spawn dummy", session)

        return spawn_dummy(session)

    if verb == "attack":
        target_name = " ".join(args).strip()
        if not target_name:
            return display_error("Usage: attack <target>", session)

        return begin_attack(session, target_name)

    if verb == "disengage":
        return disengage(session)

    if verb == "look":
        room = get_room(session.player.current_room_id)
        if room is None:
            return display_error(f"Current room not found: {session.player.current_room_id}", session)

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
        response = display_command_result(session, [
            build_part("You use ", "bright_white"),
            build_part("a heavy skill", "bright_red", True),
            build_part(". Lag applied for ", "bright_white"),
            build_part("3.0", "bright_yellow", True),
            build_part(" seconds.", "bright_white")
        ])
        apply_lag(session, 3.0)
        return response

    if verb == "say":
        spoken_text = " ".join(args).strip()
        if not spoken_text:
            return display_error("Usage: say <text>", session)

        return display_command_result(session, [
            build_part("You say, ", "bright_white"),
            build_part(f'"{spoken_text}"', "bright_magenta", True)
        ])

    if verb == "hurt":
        if not args:
            return display_error("Usage: hurt <amount>", session)
        try:
            amount = int(args[0])
        except ValueError:
            return display_error("Hurt amount must be an integer.", session)
        if amount < 0:
            return display_error("Hurt amount must be zero or greater.", session)
        return try_adjust_stat(session, [str(-amount)], "hit_points", "HP", allow_negative=True)

    if verb == "heal":
        return try_adjust_stat(session, args, "hit_points", "HP")

    if verb == "usevigor":
        if not args:
            return display_error("Usage: usevigor <amount>", session)
        try:
            amount = int(args[0])
        except ValueError:
            return display_error("Vigor amount must be an integer.", session)
        if amount < 0:
            return display_error("Vigor amount must be zero or greater.", session)
        return try_adjust_stat(session, [str(-amount)], "vigor", "Vigor", allow_negative=True)

    if verb == "restorevigor":
        return try_adjust_stat(session, args, "vigor", "Vigor")

    if verb == "gaincoins":
        return try_adjust_stat(session, args, "coins", "Coins")

    if verb == "spendcoins":
        if not args:
            return display_error("Usage: spendcoins <amount>", session)
        try:
            amount = int(args[0])
        except ValueError:
            return display_error("Coins amount must be an integer.", session)
        if amount < 0:
            return display_error("Coins amount must be zero or greater.", session)
        return try_adjust_stat(session, [str(-amount)], "coins", "Coins", allow_negative=True)

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

        return {"type": "noop"}

    return execute_command(session, input_text)


async def dispatch_message(message: dict, session: ClientSession) -> dict:
    msg_type = message["type"]

    if msg_type == "input":
        return await process_input_message(message, session)

    return display_error(f"Unsupported message type: {msg_type}")
