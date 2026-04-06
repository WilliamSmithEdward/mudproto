from . import shared as s


HandledResult = s.OutboundResult | None


def handle_world_command(
    session: s.ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb == "spawn":
        target_name = " ".join(args).strip().lower()
        if target_name != "dummy":
            return s.display_error("Usage: spawn dummy", session)

        return s.spawn_dummy(session)

    if verb in {"attack", "ki", "kil", "kill"}:
        target_name = " ".join(args).strip()
        if not target_name:
            return s.display_error(f"Usage: {verb} <target>", session)

        if session.combat.engaged_entity_ids:
            return s.display_error("You're already fighting!", session)

        return s.begin_attack(session, target_name)

    if verb == "flee":
        return s.flee(session)

    return None
