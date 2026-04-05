from . import shared as s


HandledResult = s.OutboundResult | None


_SKILL_VERBS = {"skill", "sk", "ski", "skil", "skl"}


def handle_magic_command(
    session: s.ClientSession,
    verb: str,
    args: list[str],
    command_text: str,
) -> HandledResult:
    if verb in {"spell", "spells", "sp", "spe", "spel"}:
        spells = s._list_known_spells(session)
        if not spells:
            return s.display_command_result(session, [
                s.build_part("You do not know any spells.", "bright_white"),
            ])

        menu_rows = [
            (
                str(spell.get("name", "Spell")).strip() or "Spell",
                str(spell.get("school", "Unknown")).strip() or "Unknown",
                int(spell.get("mana_cost", 0)),
            )
            for spell in spells
        ]
        return s.display_command_result(
            session,
            s._build_cost_menu_parts("Spells", menu_rows, "Mana", middle_column_header="School"),
        )

    if verb in {"skills", "sk", "ski", "skil", "skill"} and not args:
        skills = s._list_known_skills(session)
        if not skills:
            return s.display_command_result(session, [
                s.build_part("You do not know any skills.", "bright_white"),
            ])

        menu_rows = [
            (
                str(skill.get("name", "Skill")).strip() or "Skill",
                "",
                int(skill.get("vigor_cost", 0)),
            )
            for skill in skills
        ]
        return s.display_command_result(session, s._build_cost_menu_parts("Skills", menu_rows, "Vigor"))

    if verb in {"cast", "c", "ca", "cas"}:
        spell_name, target_name, parse_error = s._parse_cast_spell(command_text, args, verb)
        if parse_error is not None or spell_name is None:
            return s.display_error(parse_error or "Usage: cast 'spell name' [target]", session)

        known_spells = s._list_known_spells(session)
        if not known_spells:
            return s.display_error("You do not know any spells.", session)

        spell, resolve_error = s._resolve_spell_by_name(spell_name, known_spells)
        if spell is None:
            return s.display_error(resolve_error or f"You do not know spell: {spell_name}", session)

        response, cast_applied = s.cast_spell(session, spell, target_name)
        if cast_applied:
            if session.combat.engaged_entity_ids:
                session.combat.skip_melee_rounds = max(1, session.combat.skip_melee_rounds)
            try:
                s.apply_lag(session, s.COMBAT_ROUND_INTERVAL_SECONDS)
            except RuntimeError:
                pass
        return response

    if verb in _SKILL_VERBS:
        known_skills = s._list_known_skills(session)
        if not known_skills:
            return s.display_error("You do not know any skills.", session)

        skill_name, target_name, parse_error = s._parse_skill_use(args)
        if parse_error is not None or skill_name is None:
            return s.display_error(parse_error or "Usage: <skill> [target]", session)

        if target_name is None and len(args) > 1:
            for cut in range(len(args), 0, -1):
                candidate_skill_name = " ".join(args[:cut]).strip()
                candidate_target_name = " ".join(args[cut:]).strip() or None
                candidate_skill, _ = s._resolve_skill_by_name(candidate_skill_name, known_skills)
                if candidate_skill is not None:
                    skill_name = candidate_skill_name
                    target_name = candidate_target_name
                    break

        skill, resolve_error = s._resolve_skill_by_name(skill_name, known_skills)
        if skill is None:
            return s.display_error(resolve_error or f"Unknown skill: {skill_name}", session)

        response, skill_applied = s.use_skill(session, skill, target_name)
        if skill_applied and session.combat.engaged_entity_ids:
            lag_rounds = max(0, int(skill.get("lag_rounds", 0)))
            if lag_rounds > 0:
                try:
                    s.apply_lag(session, lag_rounds * s.COMBAT_ROUND_INTERVAL_SECONDS)
                except RuntimeError:
                    pass
        return response

    return None


def handle_skill_fallback_command(
    session: s.ClientSession,
    verb: str,
    args: list[str],
    command_text: str,
) -> HandledResult:
    known_skills = s._list_known_skills(session)
    if verb in _SKILL_VERBS | {"skills", "use"} or not known_skills:
        return None

    for cut in range(len(args) + 1, 0, -1):
        candidate_verb_args = [verb] + args[:cut - 1]
        candidate_skill_name = " ".join(candidate_verb_args).strip()
        candidate_target_name = " ".join(args[cut - 1:]).strip() or None
        candidate_skill, _ = s._resolve_skill_by_name(candidate_skill_name, known_skills)
        if candidate_skill is None:
            continue

        response, skill_applied = s.use_skill(session, candidate_skill, candidate_target_name)
        if skill_applied and session.combat.engaged_entity_ids:
            lag_rounds = max(0, int(candidate_skill.get("lag_rounds", 0)))
            if lag_rounds > 0:
                try:
                    s.apply_lag(session, lag_rounds * s.COMBAT_ROUND_INTERVAL_SECONDS)
                except RuntimeError:
                    pass
        return response

    return None
