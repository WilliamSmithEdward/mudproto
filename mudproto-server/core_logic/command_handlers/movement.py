from . import shared as s


HandledResult = s.OutboundResult | None


def handle_movement_command(
    session: s.ClientSession,
    verb: str,
    _args: list[str],
    _command_text: str,
) -> HandledResult:
    if s.normalize_direction(verb) in {"north", "south", "east", "west", "up", "down"}:
        return s.try_move(session, verb)

    return None
