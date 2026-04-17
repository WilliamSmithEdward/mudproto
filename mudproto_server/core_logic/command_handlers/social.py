import asyncio

import settings
from attribute_config import player_class_uses_mana
from combat_state import get_health_condition
from display_core import build_menu_table_parts, build_part, newline_part
from display_feedback import display_command_result, display_error
from models import ClientSession
from player_resources import get_player_resource_caps
from server_transport import send_outbound
from session_registry import connected_clients
from targeting_follow import (
    _add_group_member,
    _clear_follow_state,
    _disband_group,
    _find_followed_player_session,
    _form_group_from_followers,
    _list_group_member_sessions,
    _remove_session_from_group,
    _resolve_room_player_selector,
    _resolve_group_leader_session,
    _session_identity_key,
    _is_following_leader_recursive,
    _swap_party_positions,
    _would_create_follow_loop,
)

from .types import OutboundResult
from world import get_room


HandledResult = OutboundResult | None

_WHO_VERBS = {"wh", "who"}
_SAY_VERBS = {"sa", "say"}
_YELL_VERBS = {"ye", "yel", "yell"}
_TELL_VERBS = {"te", "tel", "tell"}
_GROUP_TELL_VERBS = {"gt"}
_SHOUT_VERBS = {"sh", "sho", "shou", "shout"}


def _display_name(session: ClientSession) -> str:
    return (session.authenticated_character_name or "").strip() or "Unknown"


def _iter_online_sessions() -> list[ClientSession]:
    return [
        candidate
        for candidate in _list_online_player_sessions()
        if candidate.is_connected and not candidate.disconnected_by_server and candidate.is_authenticated
    ]


def _send_realtime_notification(target_session: ClientSession, outbound: dict | list[dict]) -> None:
    if not target_session.is_connected or target_session.disconnected_by_server:
        return

    try:
        asyncio.get_running_loop().create_task(send_outbound(target_session.websocket, outbound))
    except RuntimeError:
        return


def _build_quote_parts(prefix: str, spoken_text: str) -> list[dict]:
    return [
        build_part(prefix, "feedback.text"),
        build_part(f'"{spoken_text}"', "feedback.text"),
    ]


def _build_actor_quote_parts(actor_name: str, verb_text: str, spoken_text: str) -> list[dict]:
    return [
        build_part(actor_name, "feedback.text"),
        build_part(f" {verb_text}, ", "feedback.text"),
        build_part(f'"{spoken_text}"', "feedback.text"),
    ]


def _display_chat_message(session: ClientSession, parts: list[dict]) -> dict:
    return display_command_result(session, parts)


def _resolve_online_player_session(selector_text: str) -> tuple[ClientSession | None, str | None]:
    normalized_selector = str(selector_text).strip().lower()
    if not normalized_selector:
        return None, "Provide a player name."

    sessions = _iter_online_sessions()
    for candidate in sessions:
        candidate_name = _display_name(candidate).strip().lower()
        if candidate_name == normalized_selector:
            return candidate, None

    for candidate in sessions:
        candidate_name = _display_name(candidate).strip().lower()
        if candidate_name.startswith(normalized_selector):
            return candidate, None

    return None, f"No online player named '{selector_text}' was found."


def _room_peer_sessions(origin_session: ClientSession) -> list[ClientSession]:
    return [
        candidate
        for candidate in _iter_online_sessions()
        if candidate.client_id != origin_session.client_id and candidate.player.current_room_id == origin_session.player.current_room_id
    ]


def _zone_peer_sessions(origin_session: ClientSession) -> list[ClientSession]:
    current_room = get_room(origin_session.player.current_room_id)
    if current_room is None:
        return []

    origin_zone_id = str(current_room.zone_id).strip().lower()
    if not origin_zone_id:
        return []

    peers: list[ClientSession] = []
    for candidate in _iter_online_sessions():
        if candidate.client_id == origin_session.client_id:
            continue
        candidate_room = get_room(candidate.player.current_room_id)
        if candidate_room is None:
            continue
        if str(candidate_room.zone_id).strip().lower() != origin_zone_id:
            continue
        peers.append(candidate)
    return peers


def _server_peer_sessions(origin_session: ClientSession) -> list[ClientSession]:
    return [candidate for candidate in _iter_online_sessions() if candidate.client_id != origin_session.client_id]


def _handle_group_tell(session: ClientSession, spoken_text: str) -> dict:
    _leader, group_sessions = _list_group_member_sessions(session)
    targets = [candidate for candidate in group_sessions if candidate.client_id != session.client_id]
    if not targets:
        return display_error("You have no group members to tell.", session)

    actor_name = _display_name(session)
    for target_session in targets:
        notification = _display_chat_message(target_session, _build_actor_quote_parts(actor_name, "tells your group", spoken_text))
        _send_realtime_notification(target_session, notification)

    return _display_chat_message(session, _build_quote_parts("You tell your group, ", spoken_text))


def _notify_follow_target(target_session: ClientSession, follower_name: str) -> None:
    if not target_session.is_connected or target_session.disconnected_by_server:
        return

    notification = display_command_result(target_session, [
        build_part(follower_name, "feedback.value", True),
        build_part(" starts following you.", "feedback.text"),
    ])

    try:
        asyncio.get_running_loop().create_task(send_outbound(target_session.websocket, notification))
    except RuntimeError:
        # No running loop: skip best-effort realtime notification.
        return


def _notify_unfollow_target(target_session: ClientSession, follower_name: str) -> None:
    if not target_session.is_connected or target_session.disconnected_by_server:
        return

    resolved_name = str(follower_name).strip() or "Someone"
    notification = display_command_result(target_session, [
        build_part(resolved_name, "feedback.value", True),
        build_part(" stops following you.", "feedback.text"),
    ])

    try:
        asyncio.get_running_loop().create_task(send_outbound(target_session.websocket, notification))
    except RuntimeError:
        return


def _notify_follow_stopped(session: ClientSession, followed_name: str) -> None:
    if not session.is_connected or session.disconnected_by_server:
        return

    resolved_name = str(followed_name).strip() or "them"
    notification = display_command_result(session, [
        build_part("You stop following ", "feedback.text"),
        build_part(resolved_name, "feedback.value", True),
        build_part(".", "feedback.text"),
    ])

    try:
        asyncio.get_running_loop().create_task(send_outbound(session.websocket, notification))
    except RuntimeError:
        return


def _swap_self_with_direct_follower(session: ClientSession, target_session: ClientSession) -> tuple[bool, str]:
    session_key = _session_identity_key(session)
    if not session_key:
        return False, "Could not determine your character identity."

    target_following_key = (target_session.following_player_key or "").strip().lower()
    if target_following_key != session_key:
        return False, "That player must be directly following you to swap outside a group."

    target_key_raw = (target_session.player_state_key or target_session.client_id).strip()
    target_name = (target_session.authenticated_character_name or "").strip() or "Unknown"

    _clear_follow_state(target_session)
    session.following_player_key = target_key_raw
    session.following_player_name = target_name
    return True, ""


def _list_online_player_sessions() -> list[ClientSession]:
    sessions = [
        candidate
        for candidate in connected_clients.values()
        if candidate.is_connected and not candidate.disconnected_by_server and candidate.is_authenticated
    ]
    sessions.sort(key=lambda candidate: (_display_name(candidate).lower(), candidate.client_id))
    return sessions


def _display_online_players(session: ClientSession) -> dict:
    online_sessions = _list_online_player_sessions()
    if not online_sessions:
        session.pending_paged_displays.clear()
        return display_command_result(session, [
            build_part("No players are currently online.", "feedback.text"),
        ])

    rows = [[_display_name(candidate)] for candidate in online_sessions]
    page_size = max(1, int(getattr(settings, "PAGINATE_TO", 10) or 10))
    page_count = (len(rows) + page_size - 1) // page_size
    page_messages: list[dict] = []

    for page_index, start in enumerate(range(0, len(rows), page_size), start=1):
        chunk = rows[start:start + page_size]
        parts = build_menu_table_parts(
            f"Players Online ({len(rows)})",
            ["Name"],
            chunk,
            column_colors=["feedback.value"],
        )
        if page_count > 1:
            parts.extend([
                newline_part(),
                build_part(f"Showing {start + 1}-{start + len(chunk)} of {len(rows)}.", "feedback.text"),
            ])
            if page_index < page_count:
                parts.extend([
                    newline_part(),
                    build_part("Press Enter for more.", "feedback.warning", True),
                ])

        page_messages.append(display_command_result(session, parts))

    session.pending_paged_displays = page_messages[1:]
    return page_messages[0]


def _build_group_status_parts(session: ClientSession) -> list[dict]:
    leader_session, member_sessions = _list_group_member_sessions(session)
    leader_key = _session_identity_key(leader_session)

    rows: list[list[str]] = []
    row_cell_colors: list[list[str]] = []
    for member_session in member_sessions:
        caps = get_player_resource_caps(member_session)
        condition, condition_color = get_health_condition(member_session.status.hit_points, caps["hit_points"])
        role = "Leader" if _session_identity_key(member_session) == leader_key else "Member"
        role_color = "feedback.warning" if role == "Leader" else "feedback.value"
        show_mana = player_class_uses_mana(member_session.player.class_id) and int(caps.get("mana", 0)) > 0
        mana_text = f"{member_session.status.mana}/{caps['mana']}" if show_mana else "-"
        rows.append([
            role,
            _display_name(member_session),
            f"{member_session.status.hit_points}/{caps['hit_points']}",
            f"{member_session.status.vigor}/{caps['vigor']}",
            mana_text,
            condition.title(),
        ])
        row_cell_colors.append([role_color, "feedback.text", "feedback.value", "feedback.value", "feedback.value", condition_color])

    return build_menu_table_parts(
        "Group Status",
        ["Role", "Name", "HP", "Vigor", "Mana", "State"],
        rows,
        row_cell_colors=row_cell_colors,
        empty_message="You have no group members.",
    )


def _resolve_group_member_by_name(leader_session: ClientSession, selector_text: str) -> ClientSession | None:
    normalized_selector = str(selector_text).strip().lower()
    if not normalized_selector:
        return None

    _, members = _list_group_member_sessions(leader_session)
    candidates = [member for member in members if member.client_id != leader_session.client_id]

    for candidate in candidates:
        if _display_name(candidate).strip().lower() == normalized_selector:
            return candidate

    for candidate in candidates:
        if _display_name(candidate).strip().lower().startswith(normalized_selector):
            return candidate

    return None


def handle_social_command(
    session: ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb in _WHO_VERBS:
        return _display_online_players(session)

    if verb in {"group", "grp", "g", "gr", "gro", "grou", "ungroup"}:
        if verb != "ungroup" and args and str(args[0]).strip().lower() == "tell":
            spoken_text = " ".join(args[1:]).strip()
            if not spoken_text:
                return display_error("Usage: group tell <text>", session)
            return _handle_group_tell(session, spoken_text)

        if verb == "ungroup":
            selector_text = " ".join(args).strip()
            if not selector_text:
                return display_error("Usage: ungroup <player>", session)

            leader_session = _resolve_group_leader_session(session)
            if leader_session.client_id != session.client_id:
                return display_error("Only the group leader can remove members.", session)

            target_session, _target_error = _resolve_room_player_selector(session, selector_text)
            if target_session is None:
                target_session = _resolve_group_member_by_name(session, selector_text)
            if target_session is None:
                return display_error(f"No group member named '{selector_text}' was found.", session)
            if target_session.client_id == session.client_id:
                return display_error("Use group disband to dissolve your group.", session)

            leader_key = _session_identity_key(session)
            target_key = _session_identity_key(target_session)
            if target_key not in session.group_member_keys or (target_session.group_leader_key or "").strip().lower() != leader_key:
                return display_error(f"{_display_name(target_session)} is not in your group.", session)

            _remove_session_from_group(target_session, notify_session=True)
            return display_command_result(session, [
                build_part("You remove ", "feedback.text"),
                build_part(_display_name(target_session), "feedback.value", True),
                build_part(" from your group.", "feedback.text"),
            ])

        if not args:
            return display_command_result(session, _build_group_status_parts(session))

        subcommand = str(args[0]).strip().lower()
        if subcommand == "form":
            leader_session = _resolve_group_leader_session(session)
            if leader_session.client_id != session.client_id:
                return display_error("Only the group leader can add members.", session)

            added_members = _form_group_from_followers(session)
            if not added_members:
                return display_error("No eligible followers to add to your group.", session)

            if len(added_members) == 1:
                return display_command_result(session, [
                    build_part("You add ", "feedback.text"),
                    build_part(_display_name(added_members[0]), "feedback.value", True),
                    build_part(" to your group.", "feedback.text"),
                ])

            return display_command_result(session, [
                build_part("You add ", "feedback.text"),
                build_part(str(len(added_members)), "feedback.value", True),
                build_part(" followers to your group.", "feedback.text"),
            ])

        if subcommand == "disband":
            leader_session = _resolve_group_leader_session(session)
            if leader_session.client_id != session.client_id:
                return display_error("Only the group leader can disband the group.", session)

            _leader, group_members = _list_group_member_sessions(session)
            removed_members = _disband_group(session, notify_members=True)
            if not removed_members:
                return display_command_result(session, [
                    build_part("Your group has only you.", "feedback.text"),
                ])

            return display_command_result(session, [
                build_part("You disband the group.", "feedback.text"),
            ])

        selector_text = " ".join(args).strip()
        leader_session = _resolve_group_leader_session(session)
        if leader_session.client_id != session.client_id:
            return display_error("Only the group leader can add members.", session)

        target_session, target_error = _resolve_room_player_selector(session, selector_text)
        if target_session is None:
            return display_error(target_error or f"No player named '{selector_text}' is here.", session)
        if target_session.client_id == session.client_id:
            return display_error("You are already in your own group.", session)
        if not _is_following_leader_recursive(target_session, session):
            return display_error(
                f"{_display_name(target_session)} must be following you before grouping.",
                session,
            )

        target_key = _session_identity_key(target_session)
        if target_key in session.group_member_keys and (target_session.group_leader_key or "").strip().lower() == _session_identity_key(session):
            return display_error(f"{_display_name(target_session)} is already in your group.", session)

        if not _add_group_member(session, target_session):
            return display_error(f"Could not add {_display_name(target_session)} to your group.", session)

        return display_command_result(session, [
            build_part("You add ", "feedback.text"),
            build_part(_display_name(target_session), "feedback.value", True),
            build_part(" to your group.", "feedback.text"),
        ])

    if verb in {"swap", "swa", "sw"}:
        if not session.authenticated_character_name:
            return display_error("You are not currently controlling a character.", session)

        if not args:
            return display_error("Usage: swap self <member> or swap <member1> with <member2>", session)

        leader_session = _resolve_group_leader_session(session)
        if leader_session.client_id != session.client_id:
            return display_error("Only the group leader can use swap.", session)

        normalized_args = [arg.strip().lower() for arg in args if arg.strip()]
        if not normalized_args:
            return display_error("Usage: swap self <member> or swap <member1> with <member2>", session)

        if normalized_args[0] in {"self", "me", "myself"}:
            if len(args) >= 3 and str(args[1]).strip().lower() == "with":
                target_selector = " ".join(args[2:]).strip()
            else:
                target_selector = " ".join(args[1:]).strip()
            if not target_selector:
                return display_error("Usage: swap self <member>", session)

            target_session = _resolve_group_member_by_name(session, target_selector)
            if target_session is None:
                target_session, _target_error = _resolve_room_player_selector(session, target_selector)
            if target_session is None:
                return display_error("That group member was not found.", session)
            if target_session.client_id == session.client_id:
                return display_error("You cannot swap yourself with yourself.", session)

            success, reason = _swap_party_positions(session, session, target_session)
            if not success:
                fallback_success, fallback_reason = _swap_self_with_direct_follower(session, target_session)
                if not fallback_success:
                    return display_error(fallback_reason or reason or "Could not swap group positions.", session)

            target_name = _display_name(target_session)
            return display_command_result(session, [
                build_part("You swap positions with ", "feedback.text"),
                build_part(target_name, "feedback.value", True),
                build_part(".", "feedback.text"),
            ])

        try:
            with_index = normalized_args.index("with")
            left_selector = " ".join(args[:with_index]).strip()
            right_selector = " ".join(args[with_index + 1 :]).strip()
        except ValueError:
            if len(args) < 2:
                return display_error("Usage: swap <member1> with <member2>", session)
            left_selector = str(args[0]).strip()
            right_selector = str(args[1]).strip()

        if not left_selector or not right_selector:
            return display_error("Usage: swap <member1> with <member2>", session)

        if right_selector.strip().lower() in {"self", "me", "myself"}:
            target_session = _resolve_group_member_by_name(session, left_selector)
            if target_session is None:
                target_session, _target_error = _resolve_room_player_selector(session, left_selector)
            if target_session is None:
                return display_error("That group member was not found.", session)
            if target_session.client_id == session.client_id:
                return display_error("You cannot swap yourself with yourself.", session)

            success, reason = _swap_party_positions(session, session, target_session)
            if not success:
                fallback_success, fallback_reason = _swap_self_with_direct_follower(session, target_session)
                if not fallback_success:
                    return display_error(fallback_reason or reason or "Could not swap group positions.", session)

            target_name = _display_name(target_session)
            return display_command_result(session, [
                build_part("You swap positions with ", "feedback.text"),
                build_part(target_name, "feedback.value", True),
                build_part(".", "feedback.text"),
            ])

        _leader, party_sessions = _list_group_member_sessions(session)
        if len(party_sessions) <= 1:
            return display_error(
                "You are not in a group. Use swap self <player> for direct follower swaps.",
                session,
            )

        first_session = _resolve_group_member_by_name(session, left_selector)
        if first_session is None:
            first_session, _first_error = _resolve_room_player_selector(session, left_selector)

        second_session = _resolve_group_member_by_name(session, right_selector)
        if second_session is None:
            second_session, _second_error = _resolve_room_player_selector(session, right_selector)

        if first_session is None or second_session is None:
            return display_error("One or both group members were not found.", session)

        if first_session.client_id == second_session.client_id:
            return display_error("You must choose two different group members.", session)

        success, reason = _swap_party_positions(session, first_session, second_session)
        if not success:
            return display_error(reason or "Could not swap group positions.", session)

        first_name = _display_name(first_session)
        second_name = _display_name(second_session)
        return display_command_result(session, [
            build_part("You swap ", "feedback.text"),
            build_part(first_name, "feedback.value", True),
            build_part(" with ", "feedback.text"),
            build_part(second_name, "feedback.value", True),
            build_part(".", "feedback.text"),
        ])

    if verb in {"watch", "unwatch"}:
        selector_text = " ".join(args).strip()
        if verb == "unwatch":
            selector_text = "off"

        if not selector_text:
            if not session.watch_player_key.strip():
                return display_error("Usage: watch <player> or watch off.", session)
            watched_name = session.watch_player_name.strip() or "someone"
            return display_command_result(session, [
                build_part("You are watching ", "feedback.text"),
                build_part(watched_name, "feedback.value", True),
                build_part(".", "feedback.text"),
            ])

        if selector_text.lower() in {"off", "stop", "none", "cancel", "clear", "me", "self", "myself"}:
            if not session.watch_player_key.strip():
                return display_error("You are not watching anyone.", session)
            watched_name = session.watch_player_name.strip() or "them"
            session.watch_player_key = ""
            session.watch_player_name = ""
            return display_command_result(session, [
                build_part("You stop watching ", "feedback.text"),
                build_part(watched_name, "feedback.value", True),
                build_part(".", "feedback.text"),
            ])

        target_session, target_error = _resolve_room_player_selector(session, selector_text)
        if target_session is None:
            return display_error(target_error or f"No player named '{selector_text}' is here.", session)
        if target_session.client_id == session.client_id:
            return display_error("You cannot watch yourself.", session)

        target_key = (target_session.player_state_key or target_session.client_id).strip()
        target_name = (target_session.authenticated_character_name or "").strip() or "Unknown"
        if session.watch_player_key.strip().lower() == target_key.lower():
            return display_error(f"You are already watching {target_name}.", session)

        session.watch_player_key = target_key
        session.watch_player_name = target_name
        return display_command_result(session, [
            build_part("You begin watching ", "feedback.text"),
            build_part(target_name, "feedback.value", True),
            build_part(".", "feedback.text"),
        ])

    if verb in {"follow", "fol", "foll", "follo", "unfollow"}:
        selector_text = " ".join(args).strip()
        if verb == "unfollow":
            selector_text = "off"

        if not selector_text:
            followed_session = _find_followed_player_session(session)
            if followed_session is None and not session.following_player_key.strip():
                return display_error("Usage: follow <player> or follow off.", session)

            followed_name = session.following_player_name.strip() or "someone"
            if followed_session is not None:
                followed_name = (followed_session.authenticated_character_name or "").strip() or followed_name

            return display_command_result(session, [
                build_part("You are following ", "feedback.text"),
                build_part(followed_name, "feedback.value", True),
                build_part(".", "feedback.text"),
            ])

        if selector_text.lower() in {"off", "stop", "none", "cancel", "clear"}:
            if not session.following_player_key.strip():
                return display_error("You are not following anyone.", session)

            followed_session = _find_followed_player_session(session)
            followed_name = session.following_player_name.strip() or "them"
            _clear_follow_state(session)
            _remove_session_from_group(session)
            if followed_session is not None:
                _notify_unfollow_target(followed_session, _display_name(session))
            return display_command_result(session, [
                build_part("You stop following ", "feedback.text"),
                build_part(followed_name, "feedback.value", True),
                build_part(".", "feedback.text"),
            ])

        if session.combat.engaged_entity_ids:
            return display_error("You cannot start following while engaged in combat.", session)

        target_session, target_error = _resolve_room_player_selector(session, selector_text)
        if target_session is None:
            return display_error(target_error or f"No player named '{selector_text}' is here.", session)
        if target_session.client_id == session.client_id:
            normalized_selector = selector_text.strip().lower()
            if normalized_selector in {"self", "me", "myself"}:
                had_group = bool(session.group_leader_key.strip())
                had_follow = bool(session.following_player_key.strip())
                previous_followed_session = _find_followed_player_session(session)
                _clear_follow_state(session)
                _remove_session_from_group(session)
                if previous_followed_session is not None and had_follow:
                    _notify_unfollow_target(previous_followed_session, _display_name(session))
                if had_group or had_follow:
                    return display_command_result(session, [
                        build_part("You stop following and leave your group.", "feedback.text"),
                    ])
                return display_error("You are already following yourself.", session)
            return display_error("You cannot follow yourself.", session)
        if _would_create_follow_loop(session, target_session):
            return display_error("You cannot create a follow loop.", session)

        target_key = (target_session.player_state_key or target_session.client_id).strip()
        target_name = (target_session.authenticated_character_name or "").strip() or "Unknown"
        previous_followed_session = _find_followed_player_session(session)
        previous_follow_key = session.following_player_key.strip().lower()
        if previous_follow_key == target_key.lower():
            return display_error(f"You are already following {target_name}.", session)

        leader_session = _resolve_group_leader_session(session)
        is_group_member = leader_session.client_id != session.client_id and bool(session.group_leader_key.strip())
        if is_group_member:
            _, group_sessions = _list_group_member_sessions(leader_session)
            group_member_keys = {
                _session_identity_key(group_session)
                for group_session in group_sessions
                if _session_identity_key(group_session)
            }
            if target_key.strip().lower() not in group_member_keys:
                _remove_session_from_group(session)

        session.following_player_key = target_key
        session.following_player_name = target_name
        if previous_followed_session is not None and previous_follow_key and previous_follow_key != target_key.lower():
            _notify_unfollow_target(previous_followed_session, _display_name(session))
        _notify_follow_target(target_session, _display_name(session))
        return display_command_result(session, [
            build_part("You start following ", "feedback.text"),
            build_part(target_name, "feedback.value", True),
            build_part(".", "feedback.text"),
        ])

    if verb in _SAY_VERBS:
        spoken_text = " ".join(args).strip()
        if not spoken_text:
            return display_error("Usage: say <text>", session)

        actor_name = _display_name(session)
        for target_session in _room_peer_sessions(session):
            notification = _display_chat_message(target_session, _build_actor_quote_parts(actor_name, "says", spoken_text))
            _send_realtime_notification(target_session, notification)

        return _display_chat_message(session, _build_quote_parts("You say, ", spoken_text))

    if verb in _YELL_VERBS:
        spoken_text = " ".join(args).strip()
        if not spoken_text:
            return display_error("Usage: yell <text>", session)

        actor_name = _display_name(session)
        for target_session in _zone_peer_sessions(session):
            notification = _display_chat_message(target_session, _build_actor_quote_parts(actor_name, "yells", spoken_text))
            _send_realtime_notification(target_session, notification)

        return _display_chat_message(session, _build_quote_parts("You yell, ", spoken_text))

    if verb in _TELL_VERBS:
        if len(args) < 2:
            return display_error("Usage: tell <player> <text>", session)

        target_selector = str(args[0]).strip()
        spoken_text = " ".join(args[1:]).strip()
        if not spoken_text:
            return display_error("Usage: tell <player> <text>", session)

        target_session, target_error = _resolve_online_player_session(target_selector)
        if target_session is None:
            return display_error(target_error or f"No online player named '{target_selector}' was found.", session)
        if target_session.client_id == session.client_id:
            return display_error("You cannot tell yourself.", session)

        actor_name = _display_name(session)
        notification = _display_chat_message(target_session, _build_actor_quote_parts(actor_name, "tells you", spoken_text))
        _send_realtime_notification(target_session, notification)

        return _display_chat_message(session, [
            build_part("You tell ", "feedback.text"),
            build_part(_display_name(target_session), "feedback.text"),
            build_part(", ", "feedback.text"),
            build_part(f'"{spoken_text}"', "feedback.text"),
        ])

    if verb in _GROUP_TELL_VERBS:
        spoken_text = " ".join(args).strip()
        if not spoken_text:
            return display_error("Usage: gt <text>", session)
        return _handle_group_tell(session, spoken_text)

    if verb in _SHOUT_VERBS:
        spoken_text = " ".join(args).strip()
        if not spoken_text:
            return display_error("Usage: shout <text>", session)

        actor_name = _display_name(session)
        for target_session in _server_peer_sessions(session):
            notification = _display_chat_message(target_session, _build_actor_quote_parts(actor_name, "shouts", spoken_text))
            _send_realtime_notification(target_session, notification)

        return _display_chat_message(session, _build_quote_parts("You shout, ", spoken_text))

    return None
