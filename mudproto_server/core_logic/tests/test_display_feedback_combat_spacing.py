from display_core import build_part
from display_feedback import display_combat_round_result, display_error
from models import ClientSession, EntityState


def _make_session(client_id: str, name: str) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    return session


def test_display_combat_round_result_does_not_prepend_blank_line() -> None:
    session = _make_session("client-combat-spacing", "Lucia")
    outbound = display_combat_round_result(session, [build_part("You strike true.")])

    payload = outbound.get("payload") if isinstance(outbound, dict) else None
    assert isinstance(payload, dict)

    lines = payload.get("lines")
    assert isinstance(lines, list)
    assert lines
    assert isinstance(lines[0], list)
    assert lines[0]

    first_line_text = "".join(str(part.get("text", "")) for part in lines[0] if isinstance(part, dict))
    assert first_line_text == "You strike true."


def test_display_error_uses_explicit_usage_code_for_lore_text() -> None:
    session = _make_session("client-display-error", "Lucia")

    outbound = display_error(
        "unused raw usage error",
        session,
        error_code="usage",
        error_context={"usage": "cast 'spark' <target>"},
    )

    payload = outbound.get("payload") if isinstance(outbound, dict) else None
    assert isinstance(payload, dict)
    lines = payload.get("lines")
    assert isinstance(lines, list)
    rendered = "\n".join(
        "".join(str(part.get("text", "")) for part in line if isinstance(part, dict))
        for line in lines
        if isinstance(line, list)
    )
    assert "You pause, trying to recall the proper form:" in rendered


def test_display_error_uses_merchant_quote_for_shop_errors() -> None:
    session = _make_session("client-display-merchant", "Lucia")
    session.entities["merchant-1"] = EntityState(
        entity_id="merchant-1",
        name="Quartermaster Vessa",
        room_id="start",
        hit_points=10,
        max_hit_points=10,
        is_alive=True,
        is_merchant=True,
    )

    outbound = display_error(
        "unused raw merchant error",
        session,
        error_code="merchant-item-unavailable",
    )

    payload = outbound.get("payload") if isinstance(outbound, dict) else None
    assert isinstance(payload, dict)
    lines = payload.get("lines")
    assert isinstance(lines, list)
    rendered = "\n".join(
        "".join(str(part.get("text", "")) for part in line if isinstance(part, dict))
        for line in lines
        if isinstance(line, list)
    )
    assert 'Quartermaster Vessa says, "I\'m sorry, I don\'t have that item."' in rendered


def test_display_error_uses_explicit_target_code_for_directional_lore() -> None:
    session = _make_session("client-display-direction", "Lucia")

    outbound = display_error(
        "unused raw target error",
        session,
        error_code="target-not-found",
        error_context={"target": "north"},
    )

    payload = outbound.get("payload") if isinstance(outbound, dict) else None
    assert isinstance(payload, dict)
    lines = payload.get("lines")
    assert isinstance(lines, list)
    rendered = "\n".join(
        "".join(str(part.get("text", "")) for part in line if isinstance(part, dict))
        for line in lines
        if isinstance(line, list)
    )
    assert "You peer to the north, but nothing there draws your eye." in rendered


def test_display_error_without_explicit_code_keeps_raw_message() -> None:
    session = _make_session("client-display-coded-target", "Lucia")

    outbound = display_error("No target named 'north' is here.", session)

    payload = outbound.get("payload") if isinstance(outbound, dict) else None
    assert isinstance(payload, dict)
    lines = payload.get("lines")
    assert isinstance(lines, list)
    rendered = "\n".join(
        "".join(str(part.get("text", "")) for part in line if isinstance(part, dict))
        for line in lines
        if isinstance(line, list)
    )
    assert "No target named 'north' is here." in rendered
    assert "You peer to the north, but nothing there draws your eye." not in rendered


def test_display_error_uses_explicit_error_code_for_merchant_quote() -> None:
    session = _make_session("client-display-coded-merchant", "Lucia")
    session.entities["merchant-1"] = EntityState(
        entity_id="merchant-1",
        name="Quartermaster Vessa",
        room_id="start",
        hit_points=10,
        max_hit_points=10,
        is_alive=True,
        is_merchant=True,
    )

    outbound = display_error(
        "unused raw merchant error",
        session,
        error_code="merchant-item-unavailable",
    )

    payload = outbound.get("payload") if isinstance(outbound, dict) else None
    assert isinstance(payload, dict)
    lines = payload.get("lines")
    assert isinstance(lines, list)
    rendered = "\n".join(
        "".join(str(part.get("text", "")) for part in line if isinstance(part, dict))
        for line in lines
        if isinstance(line, list)
    )
    assert 'Quartermaster Vessa says, "I\'m sorry, I don\'t have that item."' in rendered
