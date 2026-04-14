from display_character import display_score
from display_core import build_display, build_part, newline_part
from display_feedback import display_command_result, display_combat_round_result, display_prompt
from display_room import display_room
from models import ClientSession
from world import Room


def _make_session(client_id: str, *, authenticated: bool = True) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = authenticated
    session.is_connected = True
    session.authenticated_character_name = "Lucia"
    session.player_state_key = "lucia"
    session.player.current_room_id = "start"
    return session


def _extract_payload(outbound: dict) -> dict:
    payload = outbound.get("payload")
    assert isinstance(payload, dict)
    return payload


def _line_text(line: list[dict]) -> str:
    return "".join(str(part.get("text", "")) for part in line if isinstance(part, dict))


def test_build_display_preserves_explicit_blank_lines() -> None:
    outbound = build_display([
        newline_part(),
        build_part("hello"),
        newline_part(2),
        build_part("world"),
    ])
    payload = _extract_payload(outbound)

    lines = payload.get("lines")
    assert isinstance(lines, list)
    assert lines[0] == []
    assert _line_text(lines[1]) == "hello"
    assert lines[2] == []
    assert _line_text(lines[3]) == "World"


def test_display_prompt_uses_prompt_lines_only() -> None:
    session = _make_session("client-prompt", authenticated=False)
    outbound = display_prompt(session)
    payload = _extract_payload(outbound)

    assert payload.get("lines") == []
    prompt_lines = payload.get("prompt_lines")
    assert isinstance(prompt_lines, list)
    assert len(prompt_lines) == 1
    assert _line_text(prompt_lines[0]) == "> "


def test_display_command_result_default_has_leading_blank_and_prompt_gap() -> None:
    session = _make_session("client-command-default", authenticated=False)
    outbound = display_command_result(session, [build_part("ready")])
    payload = _extract_payload(outbound)

    lines = payload.get("lines")
    assert isinstance(lines, list)
    assert lines[0] == []
    assert _line_text(lines[1]) == "ready"

    prompt_lines = payload.get("prompt_lines")
    assert isinstance(prompt_lines, list)
    assert prompt_lines[0] == []
    assert _line_text(prompt_lines[1]) == "> "


def test_display_command_result_compact_skips_leading_blank() -> None:
    session = _make_session("client-command-compact", authenticated=False)
    outbound = display_command_result(session, [build_part("ready")], compact=True)
    payload = _extract_payload(outbound)

    lines = payload.get("lines")
    assert isinstance(lines, list)
    assert _line_text(lines[0]) == "Ready"


def test_display_combat_round_result_has_trailing_blank_line() -> None:
    session = _make_session("client-combat")
    outbound = display_combat_round_result(session, [build_part("You strike true.")])
    payload = _extract_payload(outbound)

    lines = payload.get("lines")
    assert isinstance(lines, list)
    assert _line_text(lines[0]) == "You strike true."
    assert lines[-1] == []


def test_display_room_and_score_start_with_explicit_blank_line() -> None:
    session = _make_session("client-room-score")
    room = Room(room_id="custom-room", title="Custom Room", description="A test room.")

    room_outbound = display_room(session, room)
    room_payload = _extract_payload(room_outbound)
    room_lines = room_payload.get("lines")
    assert isinstance(room_lines, list)
    assert room_lines[0] == []
    assert _line_text(room_lines[1]) == "Custom Room"

    score_outbound = display_score(session)
    score_payload = _extract_payload(score_outbound)
    score_lines = score_payload.get("lines")
    assert isinstance(score_lines, list)
    assert score_lines[0] == []

    score_prompt_lines = score_payload.get("prompt_lines")
    assert isinstance(score_prompt_lines, list)
    assert score_prompt_lines[0] == []
    assert _line_text(score_prompt_lines[1]).endswith("> ")
