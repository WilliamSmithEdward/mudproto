import command_handlers.passives as passives
from combat import _get_player_unarmed_profile
from models import ClientSession
from session_bootstrap import apply_player_class


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
