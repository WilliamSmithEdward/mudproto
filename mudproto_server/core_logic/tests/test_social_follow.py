import asyncio

import command_handlers.social as social
from models import ClientSession
from session_registry import active_character_sessions, connected_clients


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


def _register_room_pair(follower_name: str = "Ragnar", target_name: str = "Orlandu") -> tuple[ClientSession, ClientSession]:
    follower = _make_session("client-follower", follower_name)
    target = _make_session("client-target", target_name)
    connected_clients[follower.client_id] = follower
    connected_clients[target.client_id] = target
    return follower, target


def _clear_session_registries() -> None:
    connected_clients.clear()
    active_character_sessions.clear()


def test_follow_notifies_target_player_when_loop_running(monkeypatch) -> None:
    _clear_session_registries()
    follower, target = _register_room_pair()
    notifications: list[tuple[object, dict | list[dict]]] = []

    async def fake_send_outbound(websocket, outbound):
        notifications.append((websocket, outbound))
        return True

    monkeypatch.setattr(social, "send_outbound", fake_send_outbound)

    async def _scenario() -> None:
        response = social.handle_social_command(follower, "follow", ["Orlandu"], "follow Orlandu")
        assert isinstance(response, dict)
        assert "You start following Orlandu." in _extract_display_text(response)
        await asyncio.sleep(0)

    asyncio.run(_scenario())

    assert len(notifications) == 1
    assert notifications[0][0] is target.websocket
    assert "Ragnar starts following you." in _extract_display_text(notifications[0][1])

    _clear_session_registries()


def test_follow_succeeds_without_running_loop(monkeypatch) -> None:
    _clear_session_registries()
    follower, _target = _register_room_pair()
    notifications: list[tuple[object, dict | list[dict]]] = []

    async def fake_send_outbound(websocket, outbound):
        notifications.append((websocket, outbound))
        return True

    monkeypatch.setattr(social, "send_outbound", fake_send_outbound)

    response = social.handle_social_command(follower, "follow", ["Orlandu"], "follow Orlandu")
    assert isinstance(response, dict)
    assert "You start following Orlandu." in _extract_display_text(response)
    # No running loop means no realtime notification task is scheduled.
    assert notifications == []

    _clear_session_registries()
