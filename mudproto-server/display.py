from models import ClientSession
from protocol import build_response
from sessions import get_remaining_lag_seconds, is_session_lagged
from world import Room, get_room


def build_part(text: str, fg: str = "bright_white", bold: bool = False) -> dict:
    return {
        "text": text,
        "fg": fg,
        "bold": bold
    }


def build_prompt_text(session: ClientSession) -> str:
    room = get_room(session.player.current_room_id)
    exit_letters = ""

    if room is not None and room.exits:
        direction_letters = {
            "north": "N",
            "south": "S",
            "east": "E",
            "west": "W",
            "up": "U",
            "down": "D",
        }
        exit_letters = "".join(
            direction_letters[direction]
            for direction in room.exits.keys()
            if direction in direction_letters
        )

    if not exit_letters:
        exit_letters = "None"

    player = session.player
    return f"{player.hit_points}H {player.vigor}V {player.extra_lives}X {player.coins}C Exits:{exit_letters}> "


def build_display(
    parts: list[dict],
    *,
    blank_lines_before: int = 1,
    prompt_after: bool = False,
    prompt_text: str | None = None
) -> dict:
    return build_response("display", {
        "parts": parts,
        "blank_lines_before": blank_lines_before,
        "prompt_after": prompt_after,
        "prompt_text": prompt_text
    })


def display_text(
    text: str,
    *,
    fg: str = "bright_white",
    bold: bool = False,
    blank_lines_before: int = 1,
    prompt_after: bool = False,
    prompt_text: str | None = None
) -> dict:
    return build_display(
        [build_part(text, fg, bold)],
        blank_lines_before=blank_lines_before,
        prompt_after=prompt_after,
        prompt_text=prompt_text
    )


def should_show_prompt(session: ClientSession) -> bool:
    return not is_session_lagged(session)


def mark_prompt_pending(session: ClientSession) -> None:
    session.prompt_pending_after_lag = True


def resolve_prompt(session: ClientSession, prompt_after: bool) -> tuple[bool, str | None]:
    if not prompt_after:
        return False, None

    if should_show_prompt(session):
        session.prompt_pending_after_lag = False
        return True, build_prompt_text(session)

    mark_prompt_pending(session)
    return False, None


def display_prompt(session: ClientSession) -> dict:
    prompt_after, prompt_text = resolve_prompt(session, True)
    return build_display([], prompt_after=prompt_after, prompt_text=prompt_text)


def display_connected(session: ClientSession) -> dict:
    return build_display([
        build_part("Connection established. ", "bright_green", True),
        build_part("Client ID: ", "bright_white"),
        build_part(session.client_id, "bright_yellow")
    ])


def display_hello(name: str, session: ClientSession) -> dict:
    prompt_after, prompt_text = resolve_prompt(session, True)
    return build_display([
        build_part("Hello, ", "bright_green"),
        build_part(str(name), "bright_white", True)
    ], prompt_after=prompt_after, prompt_text=prompt_text)


def display_pong(session: ClientSession) -> dict:
    prompt_after, prompt_text = resolve_prompt(session, True)
    return display_text(
        "Ping received.",
        fg="bright_cyan",
        prompt_after=prompt_after,
        prompt_text=prompt_text
    )


def display_whoami(session: ClientSession) -> dict:
    remaining_lag = round(get_remaining_lag_seconds(session), 3)
    queued_count = len(session.command_queue)
    prompt_after, prompt_text = resolve_prompt(session, True)

    return build_display([
        build_part("Client ID: ", "bright_white"),
        build_part(session.client_id, "bright_yellow"),
        build_part(" | Room: ", "bright_white"),
        build_part(session.player.current_room_id, "bright_green", True),
        build_part(" | Connected: ", "bright_white"),
        build_part(session.connected_at, "bright_cyan"),
        build_part(" | Last Message: ", "bright_white"),
        build_part(str(session.last_message_at), "bright_magenta"),
        build_part(" | Lag: ", "bright_white"),
        build_part(str(remaining_lag), "bright_yellow", True),
        build_part(" | Queued: ", "bright_white"),
        build_part(str(queued_count), "bright_yellow", True)
    ], prompt_after=prompt_after, prompt_text=prompt_text)


def display_error(message: str, session: ClientSession | None = None) -> dict:
    prompt_after = False
    prompt_text = None

    if session is not None:
        prompt_after, prompt_text = resolve_prompt(session, True)

    return build_display(
        [build_part(f"Error: {message}", "bright_red", True)],
        prompt_after=prompt_after,
        prompt_text=prompt_text,
    )


def display_system(message: str) -> dict:
    return display_text(message, fg="bright_cyan")


def display_queue_ack(session: ClientSession, command_text: str) -> dict:
    mark_prompt_pending(session)
    return build_display([
        build_part("Queued: ", "bright_yellow", True),
        build_part(f'"{command_text}"', "bright_white"),
        build_part(" | Remaining lag: ", "bright_white"),
        build_part(str(round(get_remaining_lag_seconds(session), 3)), "bright_yellow", True),
        build_part(" | Queue depth: ", "bright_white"),
        build_part(str(len(session.command_queue)), "bright_magenta", True)
    ])


def display_command_result(
    session: ClientSession,
    parts: list[dict],
    *,
    blank_lines_before: int = 1,
    prompt_after: bool = True
) -> dict:
    prompt_after, prompt_text = resolve_prompt(session, prompt_after)
    return build_display(
        parts,
        blank_lines_before=blank_lines_before,
        prompt_after=prompt_after,
        prompt_text=prompt_text
    )


def display_room(session: ClientSession, room: Room) -> dict:
    prompt_after, prompt_text = resolve_prompt(session, True)
    return build_display([
        build_part(room.title, "bright_green", True),
        build_part("\n"),
        build_part(room.description, "bright_white"),
    ], prompt_after=prompt_after, prompt_text=prompt_text)
