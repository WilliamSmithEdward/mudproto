import asyncio

import command_handlers.social as social
import targeting_follow
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


def test_follow_self_notifies_previous_leader_when_loop_running(monkeypatch) -> None:
    _clear_session_registries()
    follower, target = _register_room_pair()
    follower.following_player_key = target.player_state_key
    follower.following_player_name = target.authenticated_character_name
    notifications: list[tuple[object, dict | list[dict]]] = []

    async def fake_send_outbound(websocket, outbound):
        notifications.append((websocket, outbound))
        return True

    monkeypatch.setattr(social, "send_outbound", fake_send_outbound)

    async def _scenario() -> None:
        response = social.handle_social_command(follower, "fol", ["self"], "fol self")
        assert isinstance(response, dict)
        assert "You stop following" in _extract_display_text(response)
        await asyncio.sleep(0)

    asyncio.run(_scenario())

    assert len(notifications) == 1
    assert notifications[0][0] is target.websocket
    assert "Ragnar stops following you." in _extract_display_text(notifications[0][1])

    _clear_session_registries()


def test_ungroup_suppresses_unfollow_notifications(monkeypatch) -> None:
    _clear_session_registries()
    leader = _make_session("client-leader", "Ragnar")
    member = _make_session("client-member", "Orlandu")
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
    monkeypatch.setattr(targeting_follow, "send_outbound", fake_send_outbound)

    async def _scenario() -> None:
        response = social.handle_social_command(leader, "ungroup", ["Orlandu"], "ungroup Orlandu")
        assert isinstance(response, dict)
        assert "You remove Orlandu from your group." in _extract_display_text(response)
        await asyncio.sleep(0)

    asyncio.run(_scenario())

    assert member.following_player_key == ""
    assert len(notifications) == 1
    assert notifications[0][0] is member.websocket
    assert "You stop following Ragnar." in _extract_display_text(notifications[0][1])
    assert "stops following you" not in _extract_display_text(notifications[0][1])

    _clear_session_registries()


def test_group_disband_suppresses_unfollow_notifications(monkeypatch) -> None:
    _clear_session_registries()
    leader = _make_session("client-leader", "Ragnar")
    member = _make_session("client-member", "Orlandu")
    follower = _make_session("client-follower", "Beatrix")
    for party_session in [leader, member, follower]:
        connected_clients[party_session.client_id] = party_session

    leader_key = (leader.player_state_key or leader.client_id).strip().lower()
    member_key = (member.player_state_key or member.client_id).strip().lower()
    follower_key = (follower.player_state_key or follower.client_id).strip().lower()
    leader.group_member_keys = {member_key, follower_key}
    member.group_leader_key = leader_key
    follower.group_leader_key = leader_key
    member.following_player_key = leader.player_state_key
    member.following_player_name = leader.authenticated_character_name
    follower.following_player_key = member.player_state_key
    follower.following_player_name = member.authenticated_character_name

    notifications: list[tuple[object, dict | list[dict]]] = []

    async def fake_send_outbound(websocket, outbound):
        notifications.append((websocket, outbound))
        return True

    monkeypatch.setattr(social, "send_outbound", fake_send_outbound)
    monkeypatch.setattr(targeting_follow, "send_outbound", fake_send_outbound)

    async def _scenario() -> None:
        response = social.handle_social_command(leader, "group", ["disband"], "group disband")
        assert isinstance(response, dict)
        assert "You disband the group." in _extract_display_text(response)
        await asyncio.sleep(0)

    asyncio.run(_scenario())

    notification_texts = [_extract_display_text(outbound) for _websocket, outbound in notifications]
    notified_websockets = {websocket for websocket, _outbound in notifications}
    assert notified_websockets == {member.websocket, follower.websocket}
    assert any("You stop following Ragnar." in text for text in notification_texts)
    assert any("You stop following Orlandu." in text for text in notification_texts)
    assert all("stops following you" not in text for text in notification_texts)

    _clear_session_registries()


def test_swap_self_with_party_member_reassigns_leader() -> None:
    _clear_session_registries()

    leader = _make_session("client-leader", "Ragnar")
    second = _make_session("client-second", "Orlandu")
    third = _make_session("client-third", "Beatrix")

    for party_session in [leader, second, third]:
        connected_clients[party_session.client_id] = party_session

    leader_key = (leader.player_state_key or leader.client_id).strip().lower()
    second_key = (second.player_state_key or second.client_id).strip().lower()

    leader.group_member_keys = {second_key, (third.player_state_key or third.client_id).strip().lower()}
    second.group_leader_key = leader_key
    third.group_leader_key = leader_key
    second.following_player_key = leader.player_state_key
    second.following_player_name = leader.authenticated_character_name
    third.following_player_key = second.player_state_key
    third.following_player_name = second.authenticated_character_name

    response = social.handle_social_command(leader, "swap", ["self", "Orlandu"], "swap self Orlandu")
    assert isinstance(response, dict)
    assert "You swap positions with Orlandu." in _extract_display_text(response)

    assert second.group_leader_key == ""
    assert leader.group_leader_key == second_key
    assert third.group_leader_key == second_key
    assert leader.following_player_key == second.player_state_key
    assert third.following_player_key == leader.player_state_key
    assert leader_key in second.group_member_keys

    _clear_session_registries()


def test_swap_two_party_members_updates_follow_chain() -> None:
    _clear_session_registries()

    leader = _make_session("client-leader", "Ragnar")
    second = _make_session("client-second", "Orlandu")
    third = _make_session("client-third", "Beatrix")

    for party_session in [leader, second, third]:
        connected_clients[party_session.client_id] = party_session

    leader_key = (leader.player_state_key or leader.client_id).strip().lower()
    second_key = (second.player_state_key or second.client_id).strip().lower()
    third_key = (third.player_state_key or third.client_id).strip().lower()

    leader.group_member_keys = {second_key, third_key}
    second.group_leader_key = leader_key
    third.group_leader_key = leader_key
    second.following_player_key = leader.player_state_key
    second.following_player_name = leader.authenticated_character_name
    third.following_player_key = second.player_state_key
    third.following_player_name = second.authenticated_character_name

    response = social.handle_social_command(leader, "swap", ["Orlandu", "with", "Beatrix"], "swap Orlandu with Beatrix")
    assert isinstance(response, dict)
    assert "You swap Orlandu with Beatrix." in _extract_display_text(response)

    assert third.following_player_key == leader.player_state_key
    assert second.following_player_key == third.player_state_key
    assert second.group_leader_key == leader_key
    assert third.group_leader_key == leader_key
    assert leader.group_member_keys == {second_key, third_key}

    _clear_session_registries()


def test_swap_me_member_alias_works() -> None:
    _clear_session_registries()

    leader = _make_session("client-leader", "Ragnar")
    second = _make_session("client-second", "Orlandu")
    third = _make_session("client-third", "Beatrix")

    for party_session in [leader, second, third]:
        connected_clients[party_session.client_id] = party_session

    leader_key = (leader.player_state_key or leader.client_id).strip().lower()
    second_key = (second.player_state_key or second.client_id).strip().lower()

    leader.group_member_keys = {second_key, (third.player_state_key or third.client_id).strip().lower()}
    second.group_leader_key = leader_key
    third.group_leader_key = leader_key
    second.following_player_key = leader.player_state_key
    second.following_player_name = leader.authenticated_character_name
    third.following_player_key = second.player_state_key
    third.following_player_name = second.authenticated_character_name

    response = social.handle_social_command(leader, "swap", ["me", "Orlandu"], "swap me Orlandu")
    assert isinstance(response, dict)
    assert "You swap positions with Orlandu." in _extract_display_text(response)
    assert leader.group_leader_key == second_key

    _clear_session_registries()


def test_swap_two_party_members_without_with_keyword() -> None:
    _clear_session_registries()

    leader = _make_session("client-leader", "Ragnar")
    second = _make_session("client-second", "Orlandu")
    third = _make_session("client-third", "Beatrix")

    for party_session in [leader, second, third]:
        connected_clients[party_session.client_id] = party_session

    leader_key = (leader.player_state_key or leader.client_id).strip().lower()
    second_key = (second.player_state_key or second.client_id).strip().lower()
    third_key = (third.player_state_key or third.client_id).strip().lower()

    leader.group_member_keys = {second_key, third_key}
    second.group_leader_key = leader_key
    third.group_leader_key = leader_key
    second.following_player_key = leader.player_state_key
    second.following_player_name = leader.authenticated_character_name
    third.following_player_key = second.player_state_key
    third.following_player_name = second.authenticated_character_name

    response = social.handle_social_command(leader, "swap", ["Orlandu", "Beatrix"], "swap Orlandu Beatrix")
    assert isinstance(response, dict)
    assert "You swap Orlandu with Beatrix." in _extract_display_text(response)
    assert third.following_player_key == leader.player_state_key
    assert second.following_player_key == third.player_state_key
    assert leader.group_member_keys == {second_key, third_key}

    _clear_session_registries()


def test_swap_rejected_for_non_leader_member() -> None:
    _clear_session_registries()

    leader = _make_session("client-leader", "Ragnar")
    second = _make_session("client-second", "Orlandu")
    third = _make_session("client-third", "Beatrix")

    for party_session in [leader, second, third]:
        connected_clients[party_session.client_id] = party_session

    leader_key = (leader.player_state_key or leader.client_id).strip().lower()
    second_key = (second.player_state_key or second.client_id).strip().lower()

    leader.group_member_keys = {second_key, (third.player_state_key or third.client_id).strip().lower()}
    second.group_leader_key = leader_key
    third.group_leader_key = leader_key
    second.following_player_key = leader.player_state_key
    second.following_player_name = leader.authenticated_character_name
    third.following_player_key = second.player_state_key
    third.following_player_name = second.authenticated_character_name

    response = social.handle_social_command(second, "swap", ["Ragnar", "Beatrix"], "swap Ragnar Beatrix")
    assert isinstance(response, dict)
    assert "Only the group leader can use swap." in _extract_display_text(response)

    # Ensure failed command does not mutate chain.
    assert second.group_leader_key == leader_key
    assert second.following_player_key == leader.player_state_key
    assert third.following_player_key == second.player_state_key

    _clear_session_registries()


def test_swap_requires_arguments() -> None:
    _clear_session_registries()
    leader = _make_session("client-leader", "Ragnar")
    connected_clients[leader.client_id] = leader

    response = social.handle_social_command(leader, "swap", [], "swap")
    assert isinstance(response, dict)
    assert "swap self <member> or swap <member1> with <member2>" in _extract_display_text(response)

    _clear_session_registries()


def test_swap_self_requires_target() -> None:
    _clear_session_registries()
    leader = _make_session("client-leader", "Ragnar")
    connected_clients[leader.client_id] = leader

    response = social.handle_social_command(leader, "swap", ["self"], "swap self")
    assert isinstance(response, dict)
    assert "swap self <member>" in _extract_display_text(response)

    _clear_session_registries()


def test_swap_self_unknown_member_errors_cleanly() -> None:
    _clear_session_registries()
    leader = _make_session("client-leader", "Ragnar")
    connected_clients[leader.client_id] = leader

    response = social.handle_social_command(leader, "swap", ["self", "Nobody"], "swap self Nobody")
    assert isinstance(response, dict)
    assert "That group member was not found." in _extract_display_text(response)

    _clear_session_registries()


def test_swap_rejects_same_member_targets() -> None:
    _clear_session_registries()

    leader = _make_session("client-leader", "Ragnar")
    second = _make_session("client-second", "Orlandu")
    connected_clients[leader.client_id] = leader
    connected_clients[second.client_id] = second

    leader_key = (leader.player_state_key or leader.client_id).strip().lower()
    second_key = (second.player_state_key or second.client_id).strip().lower()
    leader.group_member_keys = {second_key}
    second.group_leader_key = leader_key
    second.following_player_key = leader.player_state_key
    second.following_player_name = leader.authenticated_character_name

    response = social.handle_social_command(leader, "swap", ["Orlandu", "Orlandu"], "swap Orlandu Orlandu")
    assert isinstance(response, dict)
    assert "You must choose two different group members." in _extract_display_text(response)

    _clear_session_registries()


def test_swap_rejects_non_party_target_even_if_present_in_room() -> None:
    _clear_session_registries()

    leader = _make_session("client-leader", "Ragnar")
    second = _make_session("client-second", "Orlandu")
    outsider = _make_session("client-outsider", "Cecil")

    for party_session in [leader, second, outsider]:
        connected_clients[party_session.client_id] = party_session

    leader_key = (leader.player_state_key or leader.client_id).strip().lower()
    second_key = (second.player_state_key or second.client_id).strip().lower()
    leader.group_member_keys = {second_key}
    second.group_leader_key = leader_key
    second.following_player_key = leader.player_state_key
    second.following_player_name = leader.authenticated_character_name

    response = social.handle_social_command(leader, "swap", ["Orlandu", "Cecil"], "swap Orlandu Cecil")
    assert isinstance(response, dict)
    assert "The second swap target is not in your group order." in _extract_display_text(response)

    _clear_session_registries()


def test_swap_self_with_direct_follower_outside_party() -> None:
    _clear_session_registries()

    follower = _make_session("client-follower", "Orlandu")
    leader = _make_session("client-leader", "Ragnar")

    connected_clients[follower.client_id] = follower
    connected_clients[leader.client_id] = leader

    follower.following_player_key = leader.player_state_key
    follower.following_player_name = leader.authenticated_character_name

    response = social.handle_social_command(leader, "swap", ["self", "Orlandu"], "swap self Orlandu")
    assert isinstance(response, dict)
    assert "You swap positions with Orlandu." in _extract_display_text(response)

    assert follower.following_player_key == ""
    assert follower.following_player_name == ""
    assert leader.following_player_key == follower.player_state_key
    assert leader.following_player_name == follower.authenticated_character_name

    _clear_session_registries()


def test_swap_member_me_alias_works_for_direct_follower_outside_party() -> None:
    _clear_session_registries()

    follower = _make_session("client-follower", "Orlandu")
    leader = _make_session("client-leader", "Ragnar")

    connected_clients[follower.client_id] = follower
    connected_clients[leader.client_id] = leader

    follower.following_player_key = leader.player_state_key
    follower.following_player_name = leader.authenticated_character_name

    response = social.handle_social_command(leader, "swap", ["Orlandu", "me"], "swap Orlandu me")
    assert isinstance(response, dict)
    assert "You swap positions with Orlandu." in _extract_display_text(response)

    assert follower.following_player_key == ""
    assert follower.following_player_name == ""
    assert leader.following_player_key == follower.player_state_key
    assert leader.following_player_name == follower.authenticated_character_name

    _clear_session_registries()


def test_swap_two_targets_outside_party_shows_non_party_guidance() -> None:
    _clear_session_registries()

    leader = _make_session("client-leader", "Ragnar")
    first = _make_session("client-first", "Orlandu")
    second = _make_session("client-second", "Beatrix")

    for session in [leader, first, second]:
        connected_clients[session.client_id] = session

    response = social.handle_social_command(leader, "swap", ["Orlandu", "Beatrix"], "swap Orlandu Beatrix")
    assert isinstance(response, dict)
    assert "You are not in a group. Use swap self <player> for direct follower swaps." in _extract_display_text(response)

    _clear_session_registries()


def test_follower_is_notified_when_followed_player_dies(monkeypatch) -> None:
    _clear_session_registries()
    follower, target = _register_room_pair("Ragnar", "Orlandu")
    follower.following_player_key = target.player_state_key
    follower.following_player_name = target.authenticated_character_name

    notifications: list[tuple[object, dict | list[dict]]] = []

    async def fake_send_outbound(websocket, outbound):
        notifications.append((websocket, outbound))
        return True

    monkeypatch.setattr(targeting_follow, "send_outbound", fake_send_outbound)

    async def _scenario() -> None:
        targeting_follow._handle_player_death_follow_and_group(target)
        await asyncio.sleep(0)

    asyncio.run(_scenario())

    assert follower.following_player_key == ""
    assert len(notifications) == 1
    assert notifications[0][0] is follower.websocket
    assert "You stop following Orlandu." in _extract_display_text(notifications[0][1])

    _clear_session_registries()
