"""Combat experience and reward distribution helpers."""

from combat_text import append_newline_if_needed
from experience import award_experience
from models import ClientSession, EntityState
from player_resources import roll_level_resource_gains
from session_registry import active_character_sessions, connected_clients
from targeting_follow import _list_group_member_sessions


def _session_contributor_key(session: ClientSession) -> str:
    return (session.player_state_key or session.client_id).strip().lower()


def _mark_entity_contributor(session: ClientSession, entity: EntityState) -> None:
    contributor_key = _session_contributor_key(session)
    if contributor_key:
        entity.experience_contributor_keys.add(contributor_key)


def _append_experience_gain_notification(
    session: ClientSession,
    gained: int,
    old_level: int,
    new_level: int,
    parts: list[dict],
    build_part_fn,
) -> None:
    if gained <= 0:
        return

    append_newline_if_needed(parts)
    parts.extend([
        build_part_fn("You gain ", "bright_white"),
        build_part_fn(str(gained), "bright_cyan", True),
        build_part_fn(" experience.", "bright_white"),
    ])

    if new_level > old_level:
        resource_gains = roll_level_resource_gains(session, old_level, new_level)
        append_newline_if_needed(parts)
        parts.append(build_part_fn("\n"))
        parts.extend([
            build_part_fn("You advance to level ", "bright_green", True),
            build_part_fn(str(new_level), "bright_green", True),
            build_part_fn("!", "bright_green", True),
        ])
        append_newline_if_needed(parts)
        parts.extend([
            build_part_fn("Level gains: ", "bright_white"),
            build_part_fn(f"+{int(resource_gains.get('hit_points', 0))}HP", "bright_green", True),
            build_part_fn(" ", "bright_white"),
            build_part_fn(f"+{int(resource_gains.get('vigor', 0))}V", "bright_yellow", True),
            build_part_fn(" ", "bright_white"),
            build_part_fn(f"+{int(resource_gains.get('mana', 0))}M", "bright_cyan", True),
        ])
        parts.append(build_part_fn("\n"))
    else:
        parts.append(build_part_fn("\n"))


def _iter_experience_contributor_sessions(contributor_keys: set[str], *, room_id: str) -> list[ClientSession]:
    if not contributor_keys:
        return []

    normalized_keys = {str(key).strip().lower() for key in contributor_keys if str(key).strip()}
    normalized_room_id = str(room_id).strip()
    if not normalized_keys or not normalized_room_id:
        return []

    matched_sessions: list[ClientSession] = []
    seen_keys: set[str] = set()
    for session in list(active_character_sessions.values()) + list(connected_clients.values()):
        if not session.is_authenticated:
            continue
        if str(session.player.current_room_id).strip() != normalized_room_id:
            continue
        session_key = _session_contributor_key(session)
        if not session_key or session_key not in normalized_keys or session_key in seen_keys:
            continue
        matched_sessions.append(session)
        seen_keys.add(session_key)

    return matched_sessions


def _expand_party_keys_in_room(base_contributor_sessions: list[ClientSession], *, room_id: str) -> set[str]:
    expanded_keys: set[str] = set()
    normalized_room_id = str(room_id).strip()
    if not normalized_room_id:
        return expanded_keys

    for contributor_session in base_contributor_sessions:
        contributor_key = _session_contributor_key(contributor_session)
        if contributor_key:
            expanded_keys.add(contributor_key)

        _, party_sessions = _list_group_member_sessions(contributor_session)
        for party_session in party_sessions:
            if not party_session.is_authenticated:
                continue
            if not party_session.is_connected or party_session.disconnected_by_server:
                continue
            if str(party_session.player.current_room_id).strip() != normalized_room_id:
                continue
            party_key = _session_contributor_key(party_session)
            if party_key:
                expanded_keys.add(party_key)

    return expanded_keys


def _queue_experience_gain_notification(session: ClientSession, gained: int, old_level: int, new_level: int) -> None:
    if gained <= 0:
        return

    from display_core import build_part, parts_to_lines

    notification_parts: list[dict] = []
    _append_experience_gain_notification(
        session,
        gained,
        old_level,
        new_level,
        notification_parts,
        build_part,
    )
    notification_lines = parts_to_lines(notification_parts)
    if not notification_lines:
        return

    if session.pending_private_lines and session.pending_private_lines[-1]:
        session.pending_private_lines.append([])
    session.pending_private_lines.extend(notification_lines)


def _award_shared_entity_experience(session: ClientSession, entity: EntityState, parts: list[dict], build_part_fn) -> None:
    if bool(getattr(entity, "experience_reward_claimed", False)):
        return

    experience_reward = max(0, int(getattr(entity, "experience_reward", 0)))
    if experience_reward <= 0:
        entity.experience_reward_claimed = True
        entity.experience_contributor_keys.clear()
        return

    contributor_keys = set(getattr(entity, "experience_contributor_keys", set()))
    current_key = _session_contributor_key(session)
    if current_key:
        contributor_keys.add(current_key)

    contributor_sessions = _iter_experience_contributor_sessions(contributor_keys, room_id=entity.room_id)
    expanded_reward_keys = _expand_party_keys_in_room(contributor_sessions, room_id=entity.room_id)

    rewarded_keys: set[str] = set()
    for contributor_session in _iter_experience_contributor_sessions(expanded_reward_keys, room_id=entity.room_id):
        contributor_key = _session_contributor_key(contributor_session)
        if not contributor_key or contributor_key in rewarded_keys:
            continue

        gained, old_level, new_level, _ = award_experience(contributor_session, experience_reward)
        rewarded_keys.add(contributor_key)
        _queue_experience_gain_notification(contributor_session, gained, old_level, new_level)

    if current_key and current_key not in rewarded_keys:
        gained, old_level, new_level, _ = award_experience(session, experience_reward)
        _queue_experience_gain_notification(session, gained, old_level, new_level)

    entity.experience_reward_claimed = True
    entity.experience_contributor_keys.clear()
