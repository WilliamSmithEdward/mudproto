from abilities import _list_known_passives
from display_core import build_menu_table_parts, build_part
from display_feedback import display_command_result
from models import ClientSession
from textwrap import wrap

from .types import OutboundResult


HandledResult = OutboundResult | None

_PASSIVE_LIST_VERBS = {"passive", "passives", "pa", "pas", "pass", "passi", "passiv"}
_PASSIVE_DESCRIPTION_COLUMN_WIDTH = 58


def _build_passive_rows(passives: list[dict]) -> list[list[str]]:
    rows: list[list[str]] = []
    for passive in passives:
        passive_name = str(passive.get("name", "Passive")).strip() or "Passive"
        description = str(passive.get("description", "")).strip() or "No description."
        wrapped_description = wrap(description, width=_PASSIVE_DESCRIPTION_COLUMN_WIDTH) or [description]

        rows.append([passive_name, wrapped_description[0]])
        for continuation_line in wrapped_description[1:]:
            rows.append(["", continuation_line])

    return rows


def handle_passive_command(
    session: ClientSession,
    verb: str,
    _args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb not in _PASSIVE_LIST_VERBS:
        return None

    passives = _list_known_passives(session)
    if not passives:
        return display_command_result(session, [
            build_part("You do not know any passives.", "feedback.text"),
        ])

    rows = _build_passive_rows(passives)

    return display_command_result(
        session,
        build_menu_table_parts(
            "Passives",
            ["Name", "Description"],
            rows,
            column_colors=["feedback.value", "feedback.text"],
            column_alignments=["left", "left"],
        ),
    )
