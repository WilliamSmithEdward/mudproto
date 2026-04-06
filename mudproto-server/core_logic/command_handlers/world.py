from combat import begin_attack
from commands import OutboundResult
from display_feedback import display_error
from models import ClientSession
from world_population import spawn_dummy

from .runtime import flee


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

    return None
