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
