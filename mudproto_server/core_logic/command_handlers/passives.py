from abilities import _list_known_passives
from display_core import build_menu_table_parts, build_part
from display_feedback import display_command_result
from models import ClientSession

from .types import OutboundResult


HandledResult = OutboundResult | None

_PASSIVE_LIST_VERBS = {"passive", "passives", "pa", "pas", "pass", "passi", "passiv"}


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
            build_part("You do not know any passives.", "bright_white"),
        ])

    rows = [
        [
            str(passive.get("name", "Passive")).strip() or "Passive",
            str(passive.get("description", "")).strip() or "No description.",
        ]
        for passive in passives
    ]

    return display_command_result(
        session,
        build_menu_table_parts(
            "Passives",
            ["Name", "Description"],
            rows,
            column_colors=["bright_cyan", "bright_white"],
            column_alignments=["left", "left"],
        ),
    )
