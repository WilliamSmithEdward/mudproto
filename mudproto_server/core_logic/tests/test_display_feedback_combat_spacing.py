from display_core import build_part
from display_feedback import display_combat_round_result
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
