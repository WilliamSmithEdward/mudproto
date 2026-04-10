from combat import begin_attack
from display_feedback import display_error
from models import ClientSession
from room_actions import handle_room_keyword_action
from room_exits import handle_room_exit_command
from world_population import spawn_dummy

from .movement import flee
from .types import OutboundResult


HandledResult = OutboundResult | None


def handle_world_command(
    session: ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb == "spawn":
        target_name = " ".join(args).strip().lower()
        if target_name != "dummy":
            return display_error("Usage: spawn dummy", session)

        return spawn_dummy(session)

    if verb in {"attack", "ki", "kil", "kill"}:
        target_name = " ".join(args).strip()
        if not target_name:
            return display_error(f"Usage: {verb} <target>", session)

        if session.combat.engaged_entity_ids:
            return display_error("You're already fighting!", session)

        return begin_attack(session, target_name)

    if verb == "flee":
        return flee(session)

    room_exit_result = handle_room_exit_command(session, verb, args, _command_text)
    if room_exit_result is not None:
        return room_exit_result

    room_keyword_result = handle_room_keyword_action(session, _command_text)
    if room_keyword_result is not None:
        return room_keyword_result

    return None
