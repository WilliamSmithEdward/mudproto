from attribute_config import load_attributes
from display_character import display_equipment, display_inventory, display_score
from display_core import build_part, newline_part
from display_feedback import display_command_result
from models import ClientSession

from .types import OutboundResult


HandledResult = OutboundResult | None


def handle_character_command(
    session: ClientSession,
    verb: str,
    _args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb in {"equipment", "eq", "equi", "eqp"}:
        return display_equipment(session)

    if verb in {"inventory", "inv", "i"}:
        return display_inventory(session)

    if verb in {"attributes", "attribute", "attr", "attrs", "stats", "stat"}:
        configured_attributes = load_attributes()
        parts = [
            build_part("Attributes", "bright_white", True),
        ]

        for attribute in configured_attributes:
            attribute_id = str(attribute.get("attribute_id", "")).strip().lower()
            name = str(attribute.get("name", attribute_id)).strip() or attribute_id
            value = int(session.player.attributes.get(attribute_id, 0))
            parts.extend([
                newline_part(),
                build_part(" - ", "bright_white"),
                build_part(name, "bright_cyan", True),
                build_part(" (", "bright_white"),
                build_part(attribute_id, "bright_yellow", True),
                build_part("): ", "bright_white"),
                build_part(str(value), "bright_green", True),
            ])

        return display_command_result(session, parts)

    if verb in {"score", "scor", "sco", "sc"}:
        return display_score(session)

    return None
