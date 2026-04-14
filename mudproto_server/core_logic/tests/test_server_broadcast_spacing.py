import time
import asyncio

from display_core import build_display, build_part
from display_feedback import build_prompt_parts_default
from models import ClientSession
from server_broadcasts import _build_room_broadcast_messages, _normalize_prompt_spacing, _send_room_broadcast
from session_registry import connected_clients


def _make_session(client_id: str, name: str = "Tester") -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    session.next_game_tick_monotonic = time.monotonic() + 60
    return session


def _line_text(line: list[dict]) -> str:
    return "".join(str(part.get("text", "")) for part in line if isinstance(part, dict))


def test_normalize_prompt_spacing_uses_single_gap_after_content() -> None:
    session = _make_session("client-gap")
    prompt_lines = build_display([], prompt_after=True, prompt_parts=build_prompt_parts_default(session))["payload"]["prompt_lines"]
    payload = {
        "lines": [[build_part("A spell effect lands.")]],
        "prompt_lines": [line for line in prompt_lines if isinstance(line, list)],
    }

    _normalize_prompt_spacing(payload)

    prompt_lines = payload.get("prompt_lines")
    assert isinstance(prompt_lines, list)
    assert prompt_lines[0] == []
    assert _line_text(prompt_lines[1]).endswith("> ")


def test_normalize_prompt_spacing_does_not_double_gap_when_content_already_trailing_blank() -> None:
    session = _make_session("client-trailing")
    prompt_lines = build_display([], prompt_after=True, prompt_parts=build_prompt_parts_default(session))["payload"]["prompt_lines"]
    payload = {
        "lines": [[build_part("A spell effect lands.")], []],
        "prompt_lines": [line for line in prompt_lines if isinstance(line, list)],
    }

    _normalize_prompt_spacing(payload)

    prompt_lines = payload.get("prompt_lines")
    assert isinstance(prompt_lines, list)
    assert prompt_lines[0] != []
    assert _line_text(prompt_lines[0]).endswith("> ")


def test_room_broadcast_messages_add_at_most_one_leading_blank_line() -> None:
    origin = _make_session("client-origin", name="Lucia")
    outbound = build_display([build_part("You cast regeneration ward on you.")])

    broadcast_messages = _build_room_broadcast_messages(origin, outbound)

    assert len(broadcast_messages) == 1
    payload = broadcast_messages[0].get("payload")
    assert isinstance(payload, dict)

    lines = payload.get("lines")
    assert isinstance(lines, list)
    assert lines[0] == []
    assert lines[1] != []


def test_room_broadcast_messages_keep_single_leading_blank_if_already_present() -> None:
    origin = _make_session("client-origin-2", name="Lucia")
    outbound = build_display([
        build_part("\n"),
        build_part("You use roundhouse kick."),
    ])

    broadcast_messages = _build_room_broadcast_messages(origin, outbound)

    assert len(broadcast_messages) == 1
    payload = broadcast_messages[0].get("payload")
    assert isinstance(payload, dict)

    lines = payload.get("lines")
    assert isinstance(lines, list)
    assert lines[0] == []
    assert lines[1] != []


def test_send_room_broadcast_applies_single_prompt_gap_with_private_lines() -> None:
    origin = _make_session("client-origin-3", name="Lucia")
    peer = _make_session("client-peer-3", name="Orlandu")
    origin.player.current_room_id = "start"
    peer.player.current_room_id = "start"
    peer.pending_private_lines = [[build_part("You feel steadier.")]]

    outbound = build_display([build_part("You cast regeneration ward on you.")])
    broadcast_messages = _build_room_broadcast_messages(origin, outbound)

    sent_payloads: list[list[dict]] = []

    async def _capture_send(_websocket, message) -> None:
        sent_payloads.append(message)

    previous_clients = dict(connected_clients)
    connected_clients.clear()
    connected_clients[origin.client_id] = origin
    connected_clients[peer.client_id] = peer
    try:
        asyncio.run(_send_room_broadcast(origin, broadcast_messages, _capture_send, prompt_observers=True))
    finally:
        connected_clients.clear()
        connected_clients.update(previous_clients)

    assert len(sent_payloads) == 1
    peer_messages = sent_payloads[0]
    assert isinstance(peer_messages, list)
    assert len(peer_messages) == 1

    payload = peer_messages[0].get("payload")
    assert isinstance(payload, dict)
    lines = payload.get("lines")
    assert isinstance(lines, list)
    assert _line_text(lines[-2]).endswith("You feel steadier.")
    assert lines[-1] == []

    prompt_lines = payload.get("prompt_lines")
    assert isinstance(prompt_lines, list)
    assert _line_text(prompt_lines[0]).endswith("> ")
