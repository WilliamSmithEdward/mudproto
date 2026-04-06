from commands import OutboundResult
from models import ClientSession

from .runtime import normalize_direction, try_move


HandledResult = OutboundResult | None


def handle_movement_command(
    session: ClientSession,
    verb: str,
    _args: list[str],
    _command_text: str,
) -> HandledResult:
    if normalize_direction(verb) in {"north", "south", "east", "west", "up", "down"}:
        return try_move(session, verb)

    return None
