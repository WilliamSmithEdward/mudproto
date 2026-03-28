from models import ClientSession
from protocol import build_response
from sessions import get_remaining_lag_seconds


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