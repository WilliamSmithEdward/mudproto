"""Player-targeting and follow-state helpers."""

import re

from models import ClientSession
from session_registry import connected_clients, list_authenticated_room_players

from targeting_parsing import _selector_prefix_matches_keywords


def _resolve_room_player_selector(session: ClientSession, selector_text: str) -> tuple[ClientSession | None, str | None]:
    normalized = selector_text.strip().lower()
    if not normalized:
        return None, "Provide a target selector."

    if normalized in {"me", "self", "myself"}:
        return session, None

    room_players = list_authenticated_room_players(session.player.current_room_id)
    if not room_players:
        return None, f"No player named '{selector_text}' is here."

    query_parts = [part for part in re.findall(r"[a-zA-Z0-9]+", normalized) if part]

    if "." not in normalized:
        exact_match: ClientSession | None = None
        partial_match: ClientSession | None = None
        for player_session in room_players:
            player_name = (player_session.authenticated_character_name or "").strip().lower()
            if not player_name:
                continue

            if player_name == normalized:
                exact_match = player_session
                break

            player_keywords = {token for token in re.findall(r"[a-zA-Z0-9]+", player_name) if token}
            if _selector_prefix_matches_keywords(query_parts, player_keywords) and partial_match is None:
                partial_match = player_session

        if exact_match is not None:
            return exact_match, None
        if partial_match is not None:
            return partial_match, None
        return None, f"No player named '{selector_text}' is here."

    parts = [part for part in normalized.split(".") if part]
    if not parts:
        return None, "Provide a target selector."

    requested_index: int | None = None
    if parts[0].isdigit():
        requested_index = int(parts[0])
        parts = parts[1:]
        if requested_index <= 0:
            return None, "Selector index must be 1 or greater."

    if not parts:
        return None, "Provide at least one selector keyword after the index."

    matches: list[ClientSession] = []
    for player_session in room_players:
        player_name = (player_session.authenticated_character_name or "").strip().lower()
        keywords = {token for token in re.findall(r"[a-zA-Z0-9]+", player_name) if token}
        if _selector_prefix_matches_keywords(parts, keywords):
            matches.append(player_session)

    if not matches:
        return None, f"No player named '{selector_text}' is here."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} player match(es) found for '{selector_text}'."
        return matches[requested_index - 1], None

    return matches[0], None


def _clear_follow_state(session: ClientSession) -> None:
    session.following_player_key = ""
    session.following_player_name = ""


def _find_followed_player_session(session: ClientSession) -> ClientSession | None:
    normalized_key = (session.following_player_key or "").strip().lower()
    if not normalized_key:
        return None

    for candidate in connected_clients.values():
        if not candidate.is_connected or candidate.disconnected_by_server or not candidate.is_authenticated:
            continue
        candidate_key = (candidate.player_state_key or candidate.client_id).strip().lower()
        if candidate_key == normalized_key:
            return candidate
    return None


def _would_create_follow_loop(session: ClientSession, target_session: ClientSession) -> bool:
    follower_key = (session.player_state_key or session.client_id).strip().lower()
    if not follower_key:
        return False

    seen_keys: set[str] = {follower_key}
    current: ClientSession | None = target_session
    while current is not None:
        current_key = (current.player_state_key or current.client_id).strip().lower()
        if not current_key:
            return False
        if current_key in seen_keys:
            return True

        seen_keys.add(current_key)
        next_key = (current.following_player_key or "").strip().lower()
        if not next_key:
            return False

        current = None
        for candidate in connected_clients.values():
            if not candidate.is_connected or candidate.disconnected_by_server or not candidate.is_authenticated:
                continue
            candidate_key = (candidate.player_state_key or candidate.client_id).strip().lower()
            if candidate_key == next_key:
                current = candidate
                break

    return False


def _session_identity_key(session: ClientSession | None) -> str:
    if session is None:
        return ""
    return ((session.player_state_key or session.client_id) or "").strip().lower()


def _find_session_by_identity_key(identity_key: str) -> ClientSession | None:
    normalized_key = str(identity_key).strip().lower()
    if not normalized_key:
        return None

    for candidate in connected_clients.values():
        if not candidate.is_connected or candidate.disconnected_by_server or not candidate.is_authenticated:
            continue
        if _session_identity_key(candidate) == normalized_key:
            return candidate
    return None


def _is_following_leader(member_session: ClientSession, leader_session: ClientSession) -> bool:
    member_follow_key = (member_session.following_player_key or "").strip().lower()
    leader_key = _session_identity_key(leader_session)
    return bool(member_follow_key and leader_key and member_follow_key == leader_key)


def _is_following_leader_recursive(member_session: ClientSession, leader_session: ClientSession) -> bool:
    leader_key = _session_identity_key(leader_session)
    if not leader_key:
        return False

    member_key = _session_identity_key(member_session)
    if not member_key or member_key == leader_key:
        return False

    seen_keys: set[str] = {member_key}
    current_session: ClientSession | None = member_session

    while current_session is not None:
        next_key = (current_session.following_player_key or "").strip().lower()
        if not next_key:
            return False
        if next_key == leader_key:
            return True
        if next_key in seen_keys:
            return False

        seen_keys.add(next_key)
        current_session = _find_session_by_identity_key(next_key)

    return False


def _is_following_group_member(member_session: ClientSession, leader_session: ClientSession) -> bool:
    member_follow_key = (member_session.following_player_key or "").strip().lower()
    leader_key = _session_identity_key(leader_session)
    if not member_follow_key or not leader_key:
        return False

    if member_follow_key == leader_key:
        return True

    return member_follow_key in {
        str(member_key).strip().lower()
        for member_key in getattr(leader_session, "group_member_keys", set())
        if str(member_key).strip()
    }


def _remove_session_from_group(session: ClientSession, *, clear_follow: bool = True) -> None:
    member_key = _session_identity_key(session)
    leader_key = (session.group_leader_key or "").strip().lower()
    if not leader_key or not member_key or leader_key == member_key:
        session.group_leader_key = ""
        if clear_follow:
            _clear_follow_state(session)
        return

    leader_session = _find_session_by_identity_key(leader_key)
    if leader_session is not None:
        leader_session.group_member_keys.discard(member_key)
    session.group_leader_key = ""
    if clear_follow:
        _clear_follow_state(session)


def _disband_group(leader_session: ClientSession) -> list[ClientSession]:
    removed_members: list[ClientSession] = []
    leader_key = _session_identity_key(leader_session)
    if not leader_key:
        leader_session.group_member_keys.clear()
        leader_session.group_leader_key = ""
        return removed_members

    for member_key in list(leader_session.group_member_keys):
        member_session = _find_session_by_identity_key(member_key)
        if member_session is not None and (member_session.group_leader_key or "").strip().lower() == leader_key:
            member_session.group_leader_key = ""
            _clear_follow_state(member_session)
            removed_members.append(member_session)

    leader_session.group_member_keys.clear()
    leader_session.group_leader_key = ""
    return removed_members


def _add_group_member(leader_session: ClientSession, member_session: ClientSession) -> bool:
    leader_key = _session_identity_key(leader_session)
    member_key = _session_identity_key(member_session)
    if not leader_key or not member_key or leader_key == member_key:
        return False
    if not _is_following_leader_recursive(member_session, leader_session):
        return False

    # If this member is currently leading another group, dissolve it first.
    if member_session.group_member_keys:
        _disband_group(member_session)

    _remove_session_from_group(member_session, clear_follow=False)
    leader_session.group_member_keys.add(member_key)
    member_session.group_leader_key = leader_key
    return True


def _form_group_from_followers(leader_session: ClientSession) -> list[ClientSession]:
    added_members: list[ClientSession] = []
    leader_key = _session_identity_key(leader_session)
    if not leader_key:
        return added_members

    for candidate in connected_clients.values():
        if not candidate.is_connected or candidate.disconnected_by_server or not candidate.is_authenticated:
            continue
        if _session_identity_key(candidate) == leader_key:
            continue
        if not _is_following_leader_recursive(candidate, leader_session):
            continue
        if _add_group_member(leader_session, candidate):
            added_members.append(candidate)

    return added_members


def _resolve_group_leader_session(session: ClientSession) -> ClientSession:
    own_key = _session_identity_key(session)
    leader_key = (session.group_leader_key or "").strip().lower()

    if not leader_key or leader_key == own_key:
        session.group_leader_key = ""
        return session

    leader_session = _find_session_by_identity_key(leader_key)
    if leader_session is None:
        session.group_leader_key = ""
        return session

    if own_key not in leader_session.group_member_keys:
        session.group_leader_key = ""
        return session

    if not _is_following_group_member(session, leader_session):
        leader_session.group_member_keys.discard(own_key)
        session.group_leader_key = ""
        return session

    return leader_session


def _list_group_member_sessions(session: ClientSession) -> tuple[ClientSession, list[ClientSession]]:
    leader_session = _resolve_group_leader_session(session)
    leader_key = _session_identity_key(leader_session)
    ordered_members: list[ClientSession] = [leader_session]

    valid_member_sessions: list[ClientSession] = []
    for member_key in list(leader_session.group_member_keys):
        member_session = _find_session_by_identity_key(member_key)
        if member_session is None:
            leader_session.group_member_keys.discard(member_key)
            continue
        if not _is_following_group_member(member_session, leader_session):
            leader_session.group_member_keys.discard(member_key)
            member_session.group_leader_key = ""
            continue
        if (member_session.group_leader_key or "").strip().lower() != leader_key:
            member_session.group_leader_key = leader_key
        valid_member_sessions.append(member_session)

    valid_member_sessions.sort(key=lambda s: (s.authenticated_character_name or "").lower())
    ordered_members.extend(valid_member_sessions)
    return leader_session, ordered_members


def _handle_player_death_follow_and_group(session: ClientSession) -> None:
    """Resolve follow/group state when a player dies.

    Rules:
    - Everyone directly following the dead player stops following.
    - If the dead player led a group, direct followers of the leader are reassigned
      to the next player in that group list when possible.
    - Group membership is disbanded, but existing non-leader follow links are preserved.
    """
    deceased_key = _session_identity_key(session)
    if not deceased_key:
        return

    successor_session: ClientSession | None = None
    if session.group_member_keys:
        _, group_members = _list_group_member_sessions(session)
        eligible_successors = [
            member
            for member in group_members
            if _session_identity_key(member) != deceased_key
            and member.is_authenticated
            and member.is_connected
            and not member.disconnected_by_server
            and not member.pending_death_logout
        ]
        if eligible_successors:
            successor_session = eligible_successors[0]

    successor_key = _session_identity_key(successor_session)
    successor_name = (
        (successor_session.authenticated_character_name or "").strip() if successor_session is not None else ""
    )

    for candidate in connected_clients.values():
        if not candidate.is_authenticated or not candidate.is_connected or candidate.disconnected_by_server:
            continue
        if candidate.client_id == session.client_id:
            continue

        candidate_follow_key = (candidate.following_player_key or "").strip().lower()
        if candidate_follow_key != deceased_key:
            continue

        if successor_session is not None and candidate.client_id != successor_session.client_id and successor_key:
            candidate.following_player_key = successor_key
            candidate.following_player_name = successor_name or "Unknown"
        else:
            _clear_follow_state(candidate)

        if (candidate.watch_player_key or "").strip().lower() == deceased_key:
            candidate.watch_player_key = ""
            candidate.watch_player_name = ""

    # Clear watch state for anyone watching the dead player, even if they were not following.
    for candidate in connected_clients.values():
        if not candidate.is_authenticated or not candidate.is_connected or candidate.disconnected_by_server:
            continue
        if (candidate.watch_player_key or "").strip().lower() != deceased_key:
            continue
        candidate.watch_player_key = ""
        candidate.watch_player_name = ""

    # If the dead player was a member in another group, remove them from that roster.
    former_leader_key = (session.group_leader_key or "").strip().lower()
    if former_leader_key and former_leader_key != deceased_key:
        former_leader = _find_session_by_identity_key(former_leader_key)
        if former_leader is not None:
            former_leader.group_member_keys.discard(deceased_key)

    # Disband dead leader's group while preserving existing follow links for members.
    leader_key = deceased_key
    for member_key in list(session.group_member_keys):
        member_session = _find_session_by_identity_key(member_key)
        if member_session is None:
            continue
        if (member_session.group_leader_key or "").strip().lower() == leader_key:
            member_session.group_leader_key = ""

    session.group_member_keys.clear()
    session.group_leader_key = ""
