import asyncio

import command_handlers.social as social
from command_handlers.registry import dispatch_command
from models import ClientSession
from session_registry import active_character_sessions, connected_clients
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


def _extract_display_colors(outbound: dict | list[dict]) -> set[str]:
    messages = outbound if isinstance(outbound, list) else [outbound]
    colors: set[str] = set()
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
            for part in line:
                if isinstance(part, dict):
                    color = str(part.get("fg", "")).strip()
                    if color:
                        colors.add(color)
    return colors


def _extract_display_lines(outbound: dict | list[dict]) -> list[list[dict]]:
    messages = outbound if isinstance(outbound, list) else [outbound]
    extracted: list[list[dict]] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("type") != "display":
            continue
        payload = message.get("payload")
        if not isinstance(payload, dict):
            continue
        raw_lines = payload.get("lines", [])
        if isinstance(raw_lines, list):
            extracted.extend([line for line in raw_lines if isinstance(line, list)])
    return extracted


def _make_session(client_id: str, name: str, room_id: str) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = room_id
    return session


def _clear_session_registries() -> None:
    connected_clients.clear()
    active_character_sessions.clear()


def _install_room_map(monkeypatch) -> None:
    room_map = {
        "room-a": Room(room_id="room-a", title="Room A", description="", zone_id="zone-alpha"),
        "room-b": Room(room_id="room-b", title="Room B", description="", zone_id="zone-alpha"),
        "room-c": Room(room_id="room-c", title="Room C", description="", zone_id="zone-beta"),
    }
    monkeypatch.setattr(social, "get_room", lambda room_id: room_map.get(room_id))


def test_chat_messages_use_neutral_colors(monkeypatch) -> None:
    _clear_session_registries()
    _install_room_map(monkeypatch)

    speaker = _make_session("client-speaker", "Ragnar", "start")
    peer = _make_session("client-peer", "Orlandu", "start")
    connected_clients[speaker.client_id] = speaker
    connected_clients[peer.client_id] = peer

    notifications: list[tuple[object, dict | list[dict]]] = []

    async def fake_send_outbound(websocket, outbound):
        notifications.append((websocket, outbound))
        return True

    monkeypatch.setattr(social, "send_outbound", fake_send_outbound)

    async def _scenario() -> None:
        response = dispatch_command(speaker, "sa hello there")
        assert _extract_display_colors(response) == {"bright_white"}
        response_lines = _extract_display_lines(response)
        assert response_lines[0] == []
        assert response_lines[1] != []
        payload = response.get("payload")
        assert isinstance(payload, dict)
        prompt_lines = payload.get("prompt_lines")
        assert isinstance(prompt_lines, list)
        assert prompt_lines[0] == []
        await asyncio.sleep(0)

    asyncio.run(_scenario())

    assert len(notifications) == 1
    assert _extract_display_colors(notifications[0][1]) == {"bright_white"}
    notification_lines = _extract_display_lines(notifications[0][1])
    assert notification_lines[0] == []
    assert notification_lines[1] != []
    notification_payload = notifications[0][1].get("payload")
    assert isinstance(notification_payload, dict)
    notification_prompt_lines = notification_payload.get("prompt_lines")
    assert isinstance(notification_prompt_lines, list)
    assert notification_prompt_lines[0] == []

    _clear_session_registries()


def test_say_alias_broadcasts_to_room_peers(monkeypatch) -> None:
    _clear_session_registries()
    _install_room_map(monkeypatch)

    speaker = _make_session("client-speaker", "Ragnar", "start")
    peer = _make_session("client-peer", "Orlandu", "start")
    outsider = _make_session("client-outsider", "Beatrix", "room-b")
    for session in (speaker, peer, outsider):
        connected_clients[session.client_id] = session

    notifications: list[tuple[object, dict | list[dict]]] = []

    async def fake_send_outbound(websocket, outbound):
        notifications.append((websocket, outbound))
        return True

    monkeypatch.setattr(social, "send_outbound", fake_send_outbound)

    async def _scenario() -> None:
        response = dispatch_command(speaker, "sa hello there")
        assert "You say, \"hello there\"" in _extract_display_text(response)
        await asyncio.sleep(0)

    asyncio.run(_scenario())

    assert len(notifications) == 1
    assert notifications[0][0] is peer.websocket
    assert "Ragnar says, \"hello there\"" in _extract_display_text(notifications[0][1])
    assert outsider.websocket not in {websocket for websocket, _outbound in notifications}

    _clear_session_registries()


def test_yell_alias_broadcasts_across_zone(monkeypatch) -> None:
    _clear_session_registries()
    _install_room_map(monkeypatch)

    speaker = _make_session("client-speaker", "Ragnar", "room-a")
    same_zone = _make_session("client-same-zone", "Orlandu", "room-b")
    other_zone = _make_session("client-other-zone", "Beatrix", "room-c")
    for session in (speaker, same_zone, other_zone):
        connected_clients[session.client_id] = session

    notifications: list[tuple[object, dict | list[dict]]] = []

    async def fake_send_outbound(websocket, outbound):
        notifications.append((websocket, outbound))
        return True

    monkeypatch.setattr(social, "send_outbound", fake_send_outbound)

    async def _scenario() -> None:
        response = social.handle_social_command(speaker, "ye", ["anyone", "here"], "ye anyone here")
        assert "You yell, \"anyone here\"" in _extract_display_text(response)
        await asyncio.sleep(0)

    asyncio.run(_scenario())

    assert len(notifications) == 1
    assert notifications[0][0] is same_zone.websocket
    assert "Ragnar yells, \"anyone here\"" in _extract_display_text(notifications[0][1])
    assert other_zone.websocket not in {websocket for websocket, _outbound in notifications}

    _clear_session_registries()


def test_tell_sends_direct_message_to_named_online_player(monkeypatch) -> None:
    _clear_session_registries()
    _install_room_map(monkeypatch)

    speaker = _make_session("client-speaker", "Ragnar", "room-a")
    target = _make_session("client-target", "Orlandu", "room-c")
    observer = _make_session("client-observer", "Beatrix", "room-a")
    for session in (speaker, target, observer):
        connected_clients[session.client_id] = session

    notifications: list[tuple[object, dict | list[dict]]] = []
    response_holder: dict[str, dict | list[dict]] = {}

    async def fake_send_outbound(websocket, outbound):
        notifications.append((websocket, outbound))
        return True

    monkeypatch.setattr(social, "send_outbound", fake_send_outbound)

    async def _scenario() -> None:
        response = social.handle_social_command(speaker, "tell", ["Orlandu", "hold", "the", "line"], "tell Orlandu hold the line")
        response_holder["response"] = response
        assert "You tell Orlandu, \"hold the line\"" in _extract_display_text(response)
        assert _extract_display_colors(response) == {"bright_white"}
        await asyncio.sleep(0)

    asyncio.run(_scenario())

    assert len(notifications) == 1
    assert notifications[0][0] is target.websocket
    assert "Ragnar tells you, \"hold the line\"" in _extract_display_text(notifications[0][1])
    assert _extract_display_colors(notifications[0][1]) == {"bright_white"}
    assert observer.websocket not in {websocket for websocket, _outbound in notifications}
    assert response_holder["response"] is not None

    _clear_session_registries()


def test_group_tell_alias_broadcasts_to_group_members(monkeypatch) -> None:
    _clear_session_registries()
    _install_room_map(monkeypatch)

    leader = _make_session("client-leader", "Ragnar", "room-a")
    member = _make_session("client-member", "Orlandu", "room-c")
    outsider = _make_session("client-outsider", "Beatrix", "room-a")
    for session in (leader, member, outsider):
        connected_clients[session.client_id] = session

    leader_key = (leader.player_state_key or leader.client_id).strip().lower()
    member_key = (member.player_state_key or member.client_id).strip().lower()
    leader.group_member_keys = {member_key}
    member.group_leader_key = leader_key
    member.following_player_key = leader.player_state_key
    member.following_player_name = leader.authenticated_character_name

    notifications: list[tuple[object, dict | list[dict]]] = []

    async def fake_send_outbound(websocket, outbound):
        notifications.append((websocket, outbound))
        return True

    monkeypatch.setattr(social, "send_outbound", fake_send_outbound)

    async def _scenario() -> None:
        response = social.handle_social_command(leader, "gt", ["regroup", "at", "once"], "gt regroup at once")
        assert "You tell your group, \"regroup at once\"" in _extract_display_text(response)
        await asyncio.sleep(0)

    asyncio.run(_scenario())

    assert len(notifications) == 1
    assert notifications[0][0] is member.websocket
    assert "Ragnar tells your group, \"regroup at once\"" in _extract_display_text(notifications[0][1])
    assert outsider.websocket not in {websocket for websocket, _outbound in notifications}

    _clear_session_registries()


def test_group_tell_phrase_broadcasts_through_dispatch(monkeypatch) -> None:
    _clear_session_registries()
    _install_room_map(monkeypatch)

    leader = _make_session("client-leader", "Ragnar", "start")
    member = _make_session("client-member", "Orlandu", "room-c")
    connected_clients[leader.client_id] = leader
    connected_clients[member.client_id] = member

    leader_key = (leader.player_state_key or leader.client_id).strip().lower()
    member_key = (member.player_state_key or member.client_id).strip().lower()
    leader.group_member_keys = {member_key}
    member.group_leader_key = leader_key
    member.following_player_key = leader.player_state_key
    member.following_player_name = leader.authenticated_character_name

    notifications: list[tuple[object, dict | list[dict]]] = []

    async def fake_send_outbound(websocket, outbound):
        notifications.append((websocket, outbound))
        return True

    monkeypatch.setattr(social, "send_outbound", fake_send_outbound)

    async def _scenario() -> None:
        response = dispatch_command(leader, "group tell hold fast")
        assert "You tell your group, \"hold fast\"" in _extract_display_text(response)
        await asyncio.sleep(0)

    asyncio.run(_scenario())

    assert len(notifications) == 1
    assert notifications[0][0] is member.websocket
    assert "Ragnar tells your group, \"hold fast\"" in _extract_display_text(notifications[0][1])

    _clear_session_registries()


def test_shout_alias_broadcasts_server_wide(monkeypatch) -> None:
    _clear_session_registries()
    _install_room_map(monkeypatch)

    speaker = _make_session("client-speaker", "Ragnar", "room-a")
    recipient_one = _make_session("client-recipient-one", "Orlandu", "room-b")
    recipient_two = _make_session("client-recipient-two", "Beatrix", "room-c")
    for session in (speaker, recipient_one, recipient_two):
        connected_clients[session.client_id] = session

    notifications: list[tuple[object, dict | list[dict]]] = []

    async def fake_send_outbound(websocket, outbound):
        notifications.append((websocket, outbound))
        return True

    monkeypatch.setattr(social, "send_outbound", fake_send_outbound)

    async def _scenario() -> None:
        response = social.handle_social_command(speaker, "sh", ["server", "restart", "soon"], "sh server restart soon")
        assert "You shout, \"server restart soon\"" in _extract_display_text(response)
        await asyncio.sleep(0)

    asyncio.run(_scenario())

    assert {websocket for websocket, _outbound in notifications} == {recipient_one.websocket, recipient_two.websocket}
    notification_texts = [_extract_display_text(outbound) for _websocket, outbound in notifications]
    assert all("Ragnar shouts, \"server restart soon\"" in text for text in notification_texts)

    _clear_session_registries()
