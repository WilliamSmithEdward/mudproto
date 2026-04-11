from attribute_config import player_class_uses_mana
from combat_state import get_health_condition
from display_core import build_menu_table_parts, build_part
from display_feedback import display_command_result, display_error
from models import ClientSession
from player_resources import get_player_resource_caps
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
    _is_following_leader,
    _would_create_follow_loop,
)

from .types import OutboundResult


HandledResult = OutboundResult | None


def _display_name(session: ClientSession) -> str:
    return (session.authenticated_character_name or "").strip() or "Unknown"


def _build_group_status_parts(session: ClientSession) -> list[dict]:
    leader_session, member_sessions = _list_group_member_sessions(session)
    leader_key = _session_identity_key(leader_session)

    rows: list[list[str]] = []
    for member_session in member_sessions:
        caps = get_player_resource_caps(member_session)
        condition, _ = get_health_condition(member_session.status.hit_points, caps["hit_points"])
        role = "Leader" if _session_identity_key(member_session) == leader_key else "Member"
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

    return build_menu_table_parts(
        "Group Status",
        ["Role", "Name", "HP", "VIG", "MANA", "State"],
        rows,
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
    if verb in {"group", "grp", "ungroup"}:
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

            _remove_session_from_group(target_session)
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

            removed_members = _disband_group(session)
            if not removed_members:
                return display_command_result(session, [
                    build_part("Your group has only you.", "bright_white"),
                ])

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
        if not _is_following_leader(target_session, session):
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

        _remove_session_from_group(session)
        session.following_player_key = target_key
        session.following_player_name = target_name
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
