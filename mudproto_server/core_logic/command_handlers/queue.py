from display_core import build_part
from display_feedback import display_command_result
from models import ClientSession
from session_timing import clear_queued_commands

from .types import OutboundResult


HandledResult = OutboundResult | None
_CLEAR_QUEUE_ALIASES = {"cle", "clea", "clear"}


def is_clear_queue_command(verb: str) -> bool:
    return verb in _CLEAR_QUEUE_ALIASES


def handle_queue_command(
    session: ClientSession,
    verb: str,
    _args: list[str],
    _command_text: str,
) -> HandledResult:
    if not is_clear_queue_command(verb):
        return None

    cleared_count = clear_queued_commands(session)
    return display_command_result(session, [
        build_part("Cleared ", "bright_white"),
        build_part(str(cleared_count), "bright_cyan", True),
        build_part(" queued command", "bright_white"),
        build_part("s" if cleared_count != 1 else "", "bright_white"),
        build_part(".", "bright_white"),
    ])
