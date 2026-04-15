import asyncio

from attribute_config import player_class_uses_mana
from combat_state import get_health_condition
from display_core import build_menu_table_parts, build_part
from display_feedback import display_command_result, display_error
from models import ClientSession
from player_resources import get_player_resource_caps
from server_transport import send_outbound
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


HandledResult = OutboundResult | None


def _display_name(session: ClientSession) -> str:
    return (session.authenticated_character_name or "").strip() or "Unknown"


def _notify_follow_target(target_session: ClientSession, follower_name: str) -> None:
    if not target_session.is_connected or target_session.disconnected_by_server:
        return

    notification = display_command_result(target_session, [
        build_part(follower_name, "bright_cyan", True),
        build_part(" starts following you.", "bright_white"),
    ])

    try:
        asyncio.get_running_loop().create_task(send_outbound(target_session.websocket, notification))
    except RuntimeError:
        # No running loop: skip best-effort realtime notification.
        return


def _notify_follow_stopped(session: ClientSession, followed_name: str) -> None:
    if not session.is_connected or session.disconnected_by_server:
        return

    resolved_name = str(followed_name).strip() or "them"
    notification = display_command_result(session, [
        build_part("You no longer follow ", "bright_white"),
        build_part(resolved_name, "bright_cyan", True),
        build_part(".", "bright_white"),
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


def _build_group_status_parts(session: ClientSession) -> list[dict]:
    leader_session, member_sessions = _list_group_member_sessions(session)
    leader_key = _session_identity_key(leader_session)

    rows: list[list[str]] = []
    row_cell_colors: list[list[str]] = []
    for member_session in member_sessions:
        caps = get_player_resource_caps(member_session)
        condition, condition_color = get_health_condition(member_session.status.hit_points, caps["hit_points"])
        role = "Leader" if _session_identity_key(member_session) == leader_key else "Member"
        role_color = "bright_yellow" if role == "Leader" else "bright_cyan"
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
        row_cell_colors.append([role_color, "bright_white", "bright_cyan", "bright_cyan", "bright_cyan", condition_color])

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
    if verb in {"group", "grp", "g", "gr", "gro", "grou", "ungroup"}:
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

            previous_follow_name = target_session.following_player_name.strip() or _display_name(session)
            had_follow_target = bool(target_session.following_player_key.strip())
            _remove_session_from_group(target_session)
            if had_follow_target:
                _notify_follow_stopped(target_session, previous_follow_name)
            return display_command_result(session, [
                build_part("You remove ", "bright_white"),
                build_part(_display_name(target_session), "bright_cyan", True),
                build_part(" from your group.", "bright_white"),
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
                    build_part("You add ", "bright_white"),
                    build_part(_display_name(added_members[0]), "bright_cyan", True),
                    build_part(" to your group.", "bright_white"),
                ])

            return display_command_result(session, [
                build_part("You add ", "bright_white"),
                build_part(str(len(added_members)), "bright_cyan", True),
                build_part(" followers to your group.", "bright_white"),
            ])

        if subcommand == "disband":
            leader_session = _resolve_group_leader_session(session)
            if leader_session.client_id != session.client_id:
                return display_error("Only the group leader can disband the group.", session)

            _, group_members = _list_group_member_sessions(session)
            prior_follow_names = {
                member.client_id: (member.following_player_name.strip() or _display_name(session))
                for member in group_members
                if member.client_id != session.client_id and member.following_player_key.strip()
            }
            removed_members = _disband_group(session)
            if not removed_members:
                return display_command_result(session, [
                    build_part("Your group has only you.", "bright_white"),
                ])

            for removed_member in removed_members:
                followed_name = prior_follow_names.get(removed_member.client_id, "")
                if followed_name:
                    _notify_follow_stopped(removed_member, followed_name)

            return display_command_result(session, [
                build_part("You disband the group.", "bright_white"),
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
            build_part("You add ", "bright_white"),
            build_part(_display_name(target_session), "bright_cyan", True),
            build_part(" to your group.", "bright_white"),
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
                build_part("You swap positions with ", "bright_white"),
                build_part(target_name, "bright_cyan", True),
                build_part(".", "bright_white"),
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
                build_part("You swap positions with ", "bright_white"),
                build_part(target_name, "bright_cyan", True),
                build_part(".", "bright_white"),
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
            build_part("You swap ", "bright_white"),
            build_part(first_name, "bright_cyan", True),
            build_part(" with ", "bright_white"),
            build_part(second_name, "bright_cyan", True),
            build_part(".", "bright_white"),
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
                build_part("You are watching ", "bright_white"),
                build_part(watched_name, "bright_cyan", True),
                build_part(".", "bright_white"),
            ])

        if selector_text.lower() in {"off", "stop", "none", "cancel", "clear", "me", "self", "myself"}:
            if not session.watch_player_key.strip():
                return display_error("You are not watching anyone.", session)
            watched_name = session.watch_player_name.strip() or "them"
            session.watch_player_key = ""
            session.watch_player_name = ""
            return display_command_result(session, [
                build_part("You stop watching ", "bright_white"),
                build_part(watched_name, "bright_cyan", True),
                build_part(".", "bright_white"),
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
            build_part("You begin watching ", "bright_white"),
            build_part(target_name, "bright_cyan", True),
            build_part(".", "bright_white"),
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
                build_part("You are following ", "bright_white"),
                build_part(followed_name, "bright_cyan", True),
                build_part(".", "bright_white"),
            ])

        if selector_text.lower() in {"off", "stop", "none", "cancel", "clear"}:
            if not session.following_player_key.strip():
                return display_error("You are not following anyone.", session)

            followed_name = session.following_player_name.strip() or "them"
            _clear_follow_state(session)
            _remove_session_from_group(session)
            return display_command_result(session, [
                build_part("You stop following ", "bright_white"),
                build_part(followed_name, "bright_cyan", True),
                build_part(".", "bright_white"),
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
                _clear_follow_state(session)
                _remove_session_from_group(session)
                if had_group or had_follow:
                    return display_command_result(session, [
                        build_part("You stop following and leave your group.", "bright_white"),
                    ])
                return display_error("You are already following yourself.", session)
            return display_error("You cannot follow yourself.", session)
        if _would_create_follow_loop(session, target_session):
            return display_error("You cannot create a follow loop.", session)

        target_key = (target_session.player_state_key or target_session.client_id).strip()
        target_name = (target_session.authenticated_character_name or "").strip() or "Unknown"
        if session.following_player_key.strip().lower() == target_key.lower():
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
        _notify_follow_target(target_session, _display_name(session))
        return display_command_result(session, [
            build_part("You start following ", "bright_white"),
            build_part(target_name, "bright_cyan", True),
            build_part(".", "bright_white"),
        ])

    if verb == "say":
        spoken_text = " ".join(args).strip()
        if not spoken_text:
            return display_error("Usage: say <text>", session)

        return display_command_result(session, [
            build_part("You say, ", "bright_white"),
            build_part(f'"{spoken_text}"', "bright_magenta", True),
        ])

    return None
