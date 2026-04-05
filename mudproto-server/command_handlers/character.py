from . import shared as s


HandledResult = s.OutboundResult | None


def handle_character_command(
    session: s.ClientSession,
    verb: str,
    args: list[str],
    command_text: str,
) -> HandledResult:
    if verb in {"equipment", "eq", "equi", "eqp"}:
        return s.display_equipment(session)

    if verb in {"inventory", "inv", "i"}:
        return s.display_inventory(session)

    if verb in {"attributes", "attribute", "attr", "attrs", "stats", "stat"}:
        configured_attributes = s.load_attributes()
        parts = [
            s.build_part("Attributes", "bright_white", True),
        ]

        for attribute in configured_attributes:
            attribute_id = str(attribute.get("attribute_id", "")).strip().lower()
            name = str(attribute.get("name", attribute_id)).strip() or attribute_id
            value = int(session.player.attributes.get(attribute_id, 0))
            parts.extend([
                s.build_part("\n"),
                s.build_part(" - ", "bright_white"),
                s.build_part(name, "bright_cyan", True),
                s.build_part(" (", "bright_white"),
                s.build_part(attribute_id, "bright_yellow", True),
                s.build_part("): ", "bright_white"),
                s.build_part(str(value), "bright_green", True),
            ])

        return s.display_command_result(session, parts)

    if verb in {"score", "scor", "sco", "sc"}:
        return s.display_score(session)

    return None
