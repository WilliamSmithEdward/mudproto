from display_core import build_part
from display_feedback import display_command_result, display_error
from models import ClientSession

from .types import OutboundResult


HandledResult = OutboundResult | None

_SIT_VERBS = {"si", "sit"}
_REST_VERBS = {"r", "re", "res", "rest"}
_SLEEP_VERBS = {"sl", "sle", "slee", "sleep"}
_STAND_VERBS = {"st", "sta", "stan", "stand"}


def handle_posture_command(
    session: ClientSession,
    verb: str,
    _args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb in _SIT_VERBS:
        if session.is_sitting:
            return display_error("You are already sitting.", session)

        session.is_resting = False
        session.is_sleeping = False
        session.is_sitting = True
        return display_command_result(session, [
            build_part("You sit down.", "bright_white"),
        ])

    if verb in _REST_VERBS:
        if session.is_resting:
            return display_error("You are already resting.", session)

        session.is_sitting = False
        session.is_sleeping = False
        session.is_resting = True
        return display_command_result(session, [
            build_part("You rest your tired bones.", "bright_white"),
        ])

    if verb in _SLEEP_VERBS:
        if session.is_sleeping:
            return display_error("You are already sleeping.", session)

        session.is_sitting = False
        session.is_resting = False
        session.is_sleeping = True
        return display_command_result(session, [
            build_part("You drift off to sleep.", "bright_white"),
        ])

    if verb in _STAND_VERBS:
        if not session.is_sitting and not session.is_resting and not session.is_sleeping:
            return display_error("You are already standing.", session)

        session.is_sitting = False
        session.is_resting = False
        session.is_sleeping = False
        return display_command_result(session, [
            build_part("You stand up.", "bright_white"),
        ])

    return None
