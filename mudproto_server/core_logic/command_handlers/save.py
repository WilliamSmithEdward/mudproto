from display_core import build_part
from display_feedback import display_command_result
from models import ClientSession
from player_state_db import save_player_state

from .types import OutboundResult


HandledResult = OutboundResult | None
_SAVE_ALIASES = {"sav", "save"}


def handle_save_command(
    session: ClientSession,
    verb: str,
    _args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb not in _SAVE_ALIASES:
        return None

    save_player_state(session)
    return display_command_result(session, [
        build_part("Your progress has been saved.", "feedback.text"),
    ])
