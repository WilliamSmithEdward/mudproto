from abilities import _list_known_spells, _resolve_spell_by_name
from combat_player_abilities import cast_spell
from display_core import build_part
from display_feedback import display_command_result, display_error
from models import ClientSession
from settings import COMBAT_ROUND_INTERVAL_SECONDS
from session_timing import apply_lag
from targeting_parsing import _parse_cast_spell
from display_menus import build_cost_menu_parts

from .types import OutboundResult


HandledResult = OutboundResult | None


_SPELL_LIST_VERBS = {"spell", "spells", "sp", "spe", "spel"}
_CAST_VERBS = {"cast", "c", "ca", "cas"}


def handle_spell_command(
    session: ClientSession,
    verb: str,
    args: list[str],
    command_text: str,
) -> HandledResult:
    if verb in _SPELL_LIST_VERBS:
        spells = _list_known_spells(session)
        if not spells:
            return display_command_result(session, [
                build_part("You do not know any spells.", "feedback.text"),
            ])

        menu_rows = [
            (
                str(spell.get("name", "Spell")).strip() or "Spell",
                str(spell.get("school", "Unknown")).strip() or "Unknown",
                int(spell.get("mana_cost", 0)),
            )
            for spell in spells
        ]
        return display_command_result(
            session,
            build_cost_menu_parts("Spells", menu_rows, "Mana", middle_column_header="School"),
        )

    if verb in _CAST_VERBS:
        spell_name, target_name, parse_error = _parse_cast_spell(command_text, args, verb)
        if parse_error is not None or spell_name is None:
            return display_error(
                parse_error or "Usage: cast 'spell name' [target]",
                session,
                error_code="usage",
                error_context={"usage": "cast 'spell name' [target]"},
            )

        known_spells = _list_known_spells(session)
        if not known_spells:
            return display_error("You do not know any spells.", session)

        if target_name is None and len(args) > 1:
            for cut in range(len(args), 0, -1):
                candidate_spell_name = " ".join(args[:cut]).strip()
                candidate_target_name = " ".join(args[cut:]).strip() or None
                candidate_spell, _ = _resolve_spell_by_name(candidate_spell_name, known_spells)
                if candidate_spell is not None:
                    spell_name = candidate_spell_name
                    target_name = candidate_target_name
                    break

        spell, resolve_error = _resolve_spell_by_name(spell_name, known_spells)
        if spell is None:
            return display_error(resolve_error or f"You do not know spell: {spell_name}", session)

        response, cast_applied = cast_spell(session, spell, target_name)
        if cast_applied:
            if session.combat.engaged_entity_ids:
                session.combat.skip_melee_rounds = max(1, session.combat.skip_melee_rounds)
            try:
                apply_lag(session, COMBAT_ROUND_INTERVAL_SECONDS)
            except RuntimeError:
                pass
        return response

    return None
