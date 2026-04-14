import command_handlers.skills as skills_handler
import command_handlers.spells as spells_handler
from models import ClientSession


def _make_session(client_id: str, name: str) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    return session


def test_skill_lag_applies_even_when_skill_ends_combat(monkeypatch) -> None:
    session = _make_session("client-skill-lag", "Lucia")
    # Simulate a just-killed target flow: skill applies, but no engaged entities remain.
    session.combat.engaged_entity_ids.clear()

    bash_skill = {
        "skill_id": "skill.bash",
        "name": "Bash",
        "lag_rounds": 2,
    }

    monkeypatch.setattr(skills_handler, "_list_known_skills", lambda _session: [bash_skill])
    monkeypatch.setattr(
        skills_handler,
        "_resolve_skill_by_name",
        lambda skill_name, known_skills: (bash_skill, None) if skill_name.strip().lower() == "bash" else (None, "unknown"),
    )

    # Skill resolves successfully but leaves no engaged combatants (killed final target).
    monkeypatch.setattr(
        skills_handler,
        "use_skill",
        lambda _session, _skill, _target_name: ({"type": "display", "payload": {"lines": []}}, True),
    )

    lag_calls: list[float] = []
    monkeypatch.setattr(skills_handler, "apply_lag", lambda _session, duration_seconds: lag_calls.append(duration_seconds))

    response = skills_handler.handle_skill_fallback_command(session, "bash", ["goblin"], "bash goblin")

    assert isinstance(response, dict)
    assert lag_calls == [2 * skills_handler.COMBAT_ROUND_INTERVAL_SECONDS]


def test_spell_lag_applies_even_when_cast_ends_combat(monkeypatch) -> None:
    session = _make_session("client-spell-lag", "Lucia")
    session.combat.engaged_entity_ids.clear()

    spell = {
        "spell_id": "spell.missile",
        "name": "Magic Missile",
    }

    monkeypatch.setattr(spells_handler, "_parse_cast_spell", lambda _command_text, _args, _verb: ("magic missile", "goblin", None))
    monkeypatch.setattr(spells_handler, "_list_known_spells", lambda _session: [spell])
    monkeypatch.setattr(
        spells_handler,
        "_resolve_spell_by_name",
        lambda spell_name, known_spells: (spell, None) if spell_name.strip().lower() == "magic missile" else (None, "unknown"),
    )
    monkeypatch.setattr(
        spells_handler,
        "cast_spell",
        lambda _session, _spell, _target_name: ({"type": "display", "payload": {"lines": []}}, True),
    )

    lag_calls: list[float] = []
    monkeypatch.setattr(spells_handler, "apply_lag", lambda _session, duration_seconds: lag_calls.append(duration_seconds))

    response = spells_handler.handle_spell_command(session, "cast", ["magic", "missile", "goblin"], "cast magic missile goblin")

    assert isinstance(response, dict)
    assert lag_calls == [spells_handler.COMBAT_ROUND_INTERVAL_SECONDS]
