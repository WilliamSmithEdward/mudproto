from display_core import build_part
from display_feedback import display_command_result, display_force_prompt
from models import ClientSession
from session_timing import clear_queued_commands, is_session_lagged

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
    lagged = is_session_lagged(session)
    message = display_command_result(session, [
        build_part("Cleared ", "feedback.text"),
        build_part(str(cleared_count), "feedback.value", True),
        build_part(" queued command", "feedback.text"),
        build_part("s" if cleared_count != 1 else "", "feedback.text"),
        build_part(".", "feedback.text"),
    ], prompt_after=not lagged)

    if lagged:
        return [message, display_force_prompt(session)]

    return message
