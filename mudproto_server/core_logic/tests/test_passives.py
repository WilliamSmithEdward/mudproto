import command_handlers.passives as passives
import session_lifecycle
from combat import _get_player_unarmed_profile
from models import ClientSession
from session_bootstrap import apply_player_class
from world import Room


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


def _leading_blank_line_count(outbound: dict | list[dict]) -> int:
    message = outbound[0] if isinstance(outbound, list) and outbound else outbound
    if not isinstance(message, dict):
        return 0
    payload = message.get("payload")
    if not isinstance(payload, dict):
        return 0
    raw_lines = payload.get("lines", [])
    if not isinstance(raw_lines, list):
        return 0

    count = 0
    for line in raw_lines:
        if isinstance(line, list) and len(line) == 0:
            count += 1
            continue
        break
    return count


def _make_session(client_id: str, name: str) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    return session


def test_passive_aliases_show_menu() -> None:
    session = _make_session("client-passive", "Lucia")
    apply_player_class(session, "class.monk", roll_attributes=False, initialize_progression=False)

    for verb in ["pa", "pas", "pass", "passi", "passive", "passives"]:
        response = passives.handle_passive_command(session, verb, [], verb)
        assert isinstance(response, dict)
        text = _extract_display_text(response)
        assert "Passives" in text
        assert "Unarmed Mastery" in text
        assert "Description" in text
        assert "Your body is a practiced weapon." in text


def test_passive_description_wraps_within_description_column() -> None:
    long_description = (
        "This passive intentionally uses a long single-sentence description so the menu "
        "renderer needs to wrap it across multiple lines inside the description column."
    )
    rows = passives._build_passive_rows([
        {
            "name": "Long Passive",
            "description": long_description,
        }
    ])

    assert len(rows) >= 2
    assert rows[0][0] == "Long Passive"
    assert rows[1][0] == ""
    assert max(len(row[1]) for row in rows) <= 58


def test_passive_menu_shows_empty_state_message() -> None:
    session = _make_session("client-passive-empty", "Lucia")

    response = passives.handle_passive_command(session, "passives", [], "passives")
    assert isinstance(response, dict)
    assert "You do not know any passives." in _extract_display_text(response)


def test_passive_menu_has_single_leading_blank_line() -> None:
    session = _make_session("client-passive-spacing", "Lucia")
    apply_player_class(session, "class.monk", roll_attributes=False, initialize_progression=False)

    response = passives.handle_passive_command(session, "passives", [], "passives")
    assert isinstance(response, dict)
    assert _leading_blank_line_count(response) == 1


def test_passive_empty_message_has_single_leading_blank_line() -> None:
    session = _make_session("client-passive-spacing-empty", "Lucia")

    response = passives.handle_passive_command(session, "passives", [], "passives")
    assert isinstance(response, dict)
    assert _leading_blank_line_count(response) == 1


def test_apply_player_class_grants_starting_passives() -> None:
    arcanist = _make_session("client-arcanist", "Arcanist")
    monk = _make_session("client-monk", "Monk")

    apply_player_class(arcanist, "class.arcanist", roll_attributes=False, initialize_progression=False)
    apply_player_class(monk, "class.monk", roll_attributes=False, initialize_progression=False)

    assert arcanist.known_passive_ids == []
    assert "passive.monk-unarmed-mastery" in [value.strip().lower() for value in monk.known_passive_ids]


def test_monk_unarmed_profile_uses_passive_package() -> None:
    monk = _make_session("client-monk", "Monk")
    apply_player_class(monk, "class.monk", roll_attributes=False, initialize_progression=False)
    monk.player.attributes["dex"] = 16
    monk.player.level = 5

    unarmed_damage_bonus, unarmed_hit_bonus, dual_unarmed_attacks = _get_player_unarmed_profile(monk)

    assert unarmed_damage_bonus == 13
    assert unarmed_hit_bonus == 4
    assert dual_unarmed_attacks is True


def test_complete_login_does_not_auto_add_class_kit_passives_for_loaded_character(monkeypatch) -> None:
    session = _make_session("client-login-passive", "Lucia")

    def _fake_load_player_state(target_session, player_key=None) -> bool:
        target_session.player.class_id = "class.monk"
        target_session.known_passive_ids = []
        return True

    monkeypatch.setattr(session_lifecycle, "load_player_state", _fake_load_player_state)
    monkeypatch.setattr(session_lifecycle, "hydrate_session_from_active_character", lambda _session, _character_key: False)
    monkeypatch.setattr(session_lifecycle, "purge_nonpersistent_items", lambda _session, reason="": 0)
    monkeypatch.setattr(session_lifecycle, "clear_transient_interaction_flags_for_session", lambda _session: 0)
    monkeypatch.setattr(session_lifecycle, "register_authenticated_character_session", lambda _session: None)
    monkeypatch.setattr(session_lifecycle, "save_player_state", lambda _session, player_key=None: None)
    monkeypatch.setattr(session_lifecycle, "maybe_auto_engage_current_room", lambda _session: [])
    monkeypatch.setattr(session_lifecycle, "get_room", lambda room_id: Room(room_id=room_id, title="Start", description="A start room."))

    session_lifecycle.complete_login(
        session,
        {
            "character_key": "lucia",
            "character_name": "Lucia",
            "class_id": "class.monk",
            "gender": "female",
            "login_room_id": "start",
        },
        is_new_character=False,
    )

    assert session.known_passive_ids == []


def test_complete_login_preserves_loaded_passives_for_existing_character(monkeypatch) -> None:
    session = _make_session("client-login-passive-existing", "Lucia")

    def _fake_load_player_state(target_session, player_key=None) -> bool:
        target_session.player.class_id = "class.monk"
        target_session.known_passive_ids = ["passive.monk-unarmed-mastery"]
        return True

    monkeypatch.setattr(session_lifecycle, "load_player_state", _fake_load_player_state)
    monkeypatch.setattr(session_lifecycle, "hydrate_session_from_active_character", lambda _session, _character_key: False)
    monkeypatch.setattr(session_lifecycle, "purge_nonpersistent_items", lambda _session, reason="": 0)
    monkeypatch.setattr(session_lifecycle, "clear_transient_interaction_flags_for_session", lambda _session: 0)
    monkeypatch.setattr(session_lifecycle, "register_authenticated_character_session", lambda _session: None)
    monkeypatch.setattr(session_lifecycle, "save_player_state", lambda _session, player_key=None: None)
    monkeypatch.setattr(session_lifecycle, "maybe_auto_engage_current_room", lambda _session: [])
    monkeypatch.setattr(session_lifecycle, "get_room", lambda room_id: Room(room_id=room_id, title="Start", description="A start room."))

    session_lifecycle.complete_login(
        session,
        {
            "character_key": "lucia",
            "character_name": "Lucia",
            "class_id": "class.monk",
            "gender": "female",
            "login_room_id": "start",
        },
        is_new_character=False,
    )

    assert [value.strip().lower() for value in session.known_passive_ids] == ["passive.monk-unarmed-mastery"]


def test_hydrate_session_from_active_character_copies_known_passives() -> None:
    existing = _make_session("client-existing-passive", "Lucia")
    target = _make_session("client-target-passive", "Lucia")
    existing.player_state_key = "lucia"
    existing.known_passive_ids = ["passive.monk-unarmed-mastery"]

    previous_active = dict(session_lifecycle.active_character_sessions)
    session_lifecycle.active_character_sessions.clear()
    session_lifecycle.active_character_sessions["lucia"] = existing
    try:
        hydrated = session_lifecycle.hydrate_session_from_active_character(target, "lucia")
    finally:
        session_lifecycle.active_character_sessions.clear()
        session_lifecycle.active_character_sessions.update(previous_active)

    assert hydrated is True
    assert "passive.monk-unarmed-mastery" in [
        value.strip().lower() for value in target.known_passive_ids
    ]
