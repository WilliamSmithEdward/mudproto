import command_handlers.debug_acquire as debug_acquire
from models import ClientSession


def _extract_display_text(outbound: dict | list[dict]) -> str:
    messages = outbound if isinstance(outbound, list) else [outbound]
    lines: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("type") != "display":
            continue
        payload = message.get("payload")
        if not isinstance(payload, dict):
            continue
        raw_lines = payload.get("lines", [])
        if not isinstance(raw_lines, list):
            continue
        for line in raw_lines:
            if not isinstance(line, list):
                continue
            lines.append("".join(str(part.get("text", "")) for part in line if isinstance(part, dict)))
    return "\n".join(lines)


def _make_session(client_id: str, name: str) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    return session


def test_acquire_aliases_list_acquirable(monkeypatch) -> None:
    monkeypatch.setattr(debug_acquire, "DEBUG_MODE", True)
    monkeypatch.setattr(debug_acquire, "player_class_uses_mana", lambda _class_id: True)
    monkeypatch.setattr(debug_acquire, "load_skills", lambda: [{"skill_id": "skill.jab", "name": "Jab"}])
    monkeypatch.setattr(debug_acquire, "load_spells", lambda: [{"spell_id": "spell.spark", "name": "Spark"}])
    monkeypatch.setattr(
        debug_acquire,
        "load_passives",
        lambda: [{"passive_id": "passive.test", "name": "Test Passive"}],
    )

    session = _make_session("client-debug-list", "Lucia")

    for verb in ["ac", "acq", "acqu", "acqui"]:
        response = debug_acquire.handle_debug_acquire_command(session, verb, [], verb)
        assert isinstance(response, dict)
        text = _extract_display_text(response)
        assert "Acquirable Objects (Debug)" in text
        assert "Jab" in text
        assert "Spark" in text
        assert "Test Passive" in text


def test_acquire_grants_skill_spell_passive(monkeypatch) -> None:
    monkeypatch.setattr(debug_acquire, "DEBUG_MODE", True)
    monkeypatch.setattr(debug_acquire, "player_class_uses_mana", lambda _class_id: True)
    monkeypatch.setattr(
        debug_acquire,
        "load_skills",
        lambda: [
            {"skill_id": "skill.jab", "name": "Jab"},
        ],
    )
    monkeypatch.setattr(
        debug_acquire,
        "load_spells",
        lambda: [
            {"spell_id": "spell.spark", "name": "Spark"},
        ],
    )
    monkeypatch.setattr(
        debug_acquire,
        "load_passives",
        lambda: [
            {"passive_id": "passive.monk-unarmed-mastery", "name": "Unarmed Mastery"},
        ],
    )
    saved_calls: list[str] = []
    monkeypatch.setattr(debug_acquire, "save_player_state", lambda session: saved_calls.append(session.player_state_key))

    session = _make_session("client-debug-grant", "Lucia")

    skill_response = debug_acquire.handle_debug_acquire_command(session, "acq", ["skill", "jab"], "acq skill jab")
    assert isinstance(skill_response, dict)
    assert "Acquired skill: Jab." in _extract_display_text(skill_response)

    spell_response = debug_acquire.handle_debug_acquire_command(session, "acq", ["spell", "spark"], "acq spell spark")
    assert isinstance(spell_response, dict)
    assert "Acquired spell: Spark." in _extract_display_text(spell_response)

    passive_response = debug_acquire.handle_debug_acquire_command(
        session,
        "acq",
        ["passive", "unarmed"],
        "acq passive unarmed",
    )
    assert isinstance(passive_response, dict)
    assert "Acquired passive: Unarmed Mastery." in _extract_display_text(passive_response)

    assert "skill.jab" in [value.strip().lower() for value in session.known_skill_ids]
    assert "spell.spark" in [value.strip().lower() for value in session.known_spell_ids]
    assert "passive.monk-unarmed-mastery" in [value.strip().lower() for value in session.known_passive_ids]
    assert saved_calls == ["lucia", "lucia", "lucia"]


def test_acquire_spell_blocked_for_non_mana_class(monkeypatch) -> None:
    monkeypatch.setattr(debug_acquire, "DEBUG_MODE", True)
    monkeypatch.setattr(debug_acquire, "player_class_uses_mana", lambda _class_id: False)
    monkeypatch.setattr(debug_acquire, "load_skills", lambda: [])
    monkeypatch.setattr(debug_acquire, "load_spells", lambda: [{"spell_id": "spell.spark", "name": "Spark"}])
    monkeypatch.setattr(debug_acquire, "load_passives", lambda: [])

    session = _make_session("client-debug-no-mana", "Lucia")
    response = debug_acquire.handle_debug_acquire_command(session, "ac", ["spell", "spark"], "ac spell spark")

    assert isinstance(response, dict)
    assert "Your class cannot acquire spells because it does not use mana." in _extract_display_text(response)


def test_forget_aliases_remove_known_entries(monkeypatch) -> None:
    monkeypatch.setattr(debug_acquire, "DEBUG_MODE", True)
    monkeypatch.setattr(debug_acquire, "player_class_uses_mana", lambda _class_id: True)
    monkeypatch.setattr(debug_acquire, "load_skills", lambda: [{"skill_id": "skill.jab", "name": "Jab"}])
    monkeypatch.setattr(debug_acquire, "load_spells", lambda: [{"spell_id": "spell.spark", "name": "Spark"}])
    monkeypatch.setattr(
        debug_acquire,
        "load_passives",
        lambda: [{"passive_id": "passive.monk-unarmed-mastery", "name": "Unarmed Mastery"}],
    )
    saved_calls: list[str] = []
    monkeypatch.setattr(debug_acquire, "save_player_state", lambda session: saved_calls.append(session.player_state_key))

    session = _make_session("client-debug-forget", "Lucia")
    session.known_skill_ids = ["skill.jab"]
    session.known_spell_ids = ["spell.spark"]
    session.known_passive_ids = ["passive.monk-unarmed-mastery"]

    skill_response = debug_acquire.handle_debug_acquire_command(session, "fo", ["jab"], "fo jab")
    assert isinstance(skill_response, dict)
    assert "Forgot skill: Jab." in _extract_display_text(skill_response)

    spell_response = debug_acquire.handle_debug_acquire_command(session, "for", ["spark"], "for spark")
    assert isinstance(spell_response, dict)
    assert "Forgot spell: Spark." in _extract_display_text(spell_response)

    passive_response = debug_acquire.handle_debug_acquire_command(
        session,
        "forg",
        ["unarmed"],
        "forg unarmed",
    )
    assert isinstance(passive_response, dict)
    assert "Forgot passive: Unarmed Mastery." in _extract_display_text(passive_response)

    assert session.known_skill_ids == []
    assert session.known_spell_ids == []
    assert session.known_passive_ids == []
    assert saved_calls == ["lucia", "lucia", "lucia"]


def test_debug_mode_off_rejects_commands(monkeypatch) -> None:
    monkeypatch.setattr(debug_acquire, "DEBUG_MODE", False)
    session = _make_session("client-debug-off", "Lucia")

    response = debug_acquire.handle_debug_acquire_command(session, "ac", [], "ac")
    assert isinstance(response, dict)
    assert "Debug mode is disabled." in _extract_display_text(response)
