from abilities import _list_known_skills, _resolve_skill_by_name
from combat_player_abilities import use_skill
from display_core import build_part
from display_feedback import display_command_result, display_error
from models import ClientSession
from settings import COMBAT_ROUND_INTERVAL_SECONDS
from session_timing import apply_lag
from targeting_parsing import _parse_skill_use
from display_menus import build_cost_menu_parts

from .types import OutboundResult


HandledResult = OutboundResult | None


# Skill execution is name-driven via fallback (for example: `jab scout`).
# Verb forms like `skill <name>` are intentionally invalid, but
# `sk`/`ski`/`skil`/`skill` with no args show the skills menu.
_SKILL_VERBS: set[str] = set()
_SKILL_MENU_VERBS = {"skills", "sk", "ski", "skil", "skill"}


def handle_skill_command(
    session: ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb in _SKILL_MENU_VERBS and not args:
        skills = _list_known_skills(session)
        if not skills:
            return display_command_result(session, [
                build_part("You do not know any skills.", "bright_white"),
            ])

        menu_rows = [
            (
                str(skill.get("name", "Skill")).strip() or "Skill",
                "",
                int(skill.get("vigor_cost", 0)),
            )
            for skill in skills
        ]
        return display_command_result(session, build_cost_menu_parts("Skills", menu_rows, "Vigor"))

    if verb in _SKILL_VERBS:
        known_skills = _list_known_skills(session)
        if not known_skills:
            return display_error("You do not know any skills.", session)

        skill_name, target_name, parse_error = _parse_skill_use(args)
        if parse_error is not None or skill_name is None:
            return display_error(
                parse_error or "Usage: <skill> [target]",
                session,
                error_code="usage",
                error_context={"usage": "<skill> [target]"},
            )

        if target_name is None and len(args) > 1:
            for cut in range(len(args), 0, -1):
                candidate_skill_name = " ".join(args[:cut]).strip()
                candidate_target_name = " ".join(args[cut:]).strip() or None
                candidate_skill, _ = _resolve_skill_by_name(candidate_skill_name, known_skills)
                if candidate_skill is not None:
                    skill_name = candidate_skill_name
                    target_name = candidate_target_name
                    break

        skill, resolve_error = _resolve_skill_by_name(skill_name, known_skills)
        if skill is None:
            return display_error(resolve_error or f"Unknown skill: {skill_name}", session)

        response, skill_applied = use_skill(session, skill, target_name)
        if skill_applied:
            lag_rounds = max(0, int(skill.get("lag_rounds", 0)))
            if lag_rounds > 0:
                try:
                    apply_lag(session, lag_rounds * COMBAT_ROUND_INTERVAL_SECONDS)
                except RuntimeError:
                    pass
        return response

    return None


def handle_skill_fallback_command(
    session: ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> HandledResult:
    known_skills = _list_known_skills(session)
    if verb in {"skills", "use"} or not known_skills:
        return None

    for cut in range(len(args) + 1, 0, -1):
        candidate_verb_args = [verb] + args[:cut - 1]
        candidate_skill_name = " ".join(candidate_verb_args).strip()
        candidate_target_name = " ".join(args[cut - 1:]).strip() or None
        candidate_skill, _ = _resolve_skill_by_name(candidate_skill_name, known_skills)
        if candidate_skill is None:
            continue

        response, skill_applied = use_skill(session, candidate_skill, candidate_target_name)
        if skill_applied:
            lag_rounds = max(0, int(candidate_skill.get("lag_rounds", 0)))
            if lag_rounds > 0:
                try:
                    apply_lag(session, lag_rounds * COMBAT_ROUND_INTERVAL_SECONDS)
                except RuntimeError:
                    pass
        return response

    return None
