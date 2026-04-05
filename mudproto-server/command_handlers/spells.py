from . import shared as s


HandledResult = s.OutboundResult | None


_SPELL_LIST_VERBS = {"spell", "spells", "sp", "spe", "spel"}
_CAST_VERBS = {"cast", "c", "ca", "cas"}


def handle_spell_command(
    session: s.ClientSession,
    verb: str,
    args: list[str],
    command_text: str,
) -> HandledResult:
    if verb in _SPELL_LIST_VERBS:
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

    if verb in _CAST_VERBS:
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

    return None
