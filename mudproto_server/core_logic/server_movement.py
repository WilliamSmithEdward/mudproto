"""Movement, room notices, and follow propagation helpers for `server.py`."""

import json

from combat_state import maybe_auto_engage_current_room
from display_core import build_display, build_line, build_part, newline_part
from display_feedback import build_prompt_parts, display_error
from display_room import display_room
from models import ClientSession
from room_actions import get_room_enter_communications, insert_room_communication_lines
from session_registry import connected_clients
from world import get_room

from server_broadcasts import _iter_room_sessions


DIRECTION_OPPOSITES = {
    "north": "south",
    "south": "north",
    "east": "west",
    "west": "east",
    "up": "down",
    "down": "up",
}


def _format_arrival_origin(direction: str) -> str:
    normalized = str(direction).strip().lower()
    if normalized == "up":
        return "above"
    if normalized == "down":
        return "below"
    if normalized in {"north", "south", "east", "west"}:
        return f"the {normalized}"
    return normalized or "somewhere"


def _extract_movement_events(outbound: dict | list[dict]) -> list[dict[str, object]]:
    messages = outbound if isinstance(outbound, list) else [outbound]
    movement_events: list[dict[str, object]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        payload = message.get("payload")
        if not isinstance(payload, dict):
            continue
        movement = payload.get("movement")
        if isinstance(movement, dict):
            movement_events.append(movement)
    return movement_events


def _prepend_display_lines(message: dict | None, lines: list[list[dict]]) -> dict | None:
    if not isinstance(message, dict):
        return message

    payload = message.get("payload")
    if not isinstance(payload, dict):
        return message

    normalized_prefix = [line for line in lines if isinstance(line, list)]
    existing_lines = payload.get("lines")
    if isinstance(existing_lines, list):
        normalized_existing = [line for line in existing_lines if isinstance(line, list)]
        while normalized_prefix and normalized_existing and not normalized_prefix[-1] and not normalized_existing[0]:
            normalized_existing.pop(0)
        payload["lines"] = normalized_prefix + normalized_existing
    else:
        payload["lines"] = normalized_prefix
    return message


def _message_lines(messages: list[dict] | list[str], *, audience_filter: set[str] | None = None) -> list[list[dict]]:
    allowed_audiences = {str(value).strip().lower() for value in (audience_filter or {"private", "both", "room"}) if str(value).strip()}
    lines: list[list[dict]] = []
    for message in messages:
        if isinstance(message, dict):
            audience = str(message.get("audience", "both")).strip().lower() or "both"
            if audience not in allowed_audiences:
                continue
            cleaned = str(message.get("message", "")).strip()
        else:
            cleaned = str(message).strip()
        if not cleaned:
            continue
        lines.append(build_line(build_part(cleaned, "bright_white")))
    if lines:
        lines.append([])
    return lines


def _refresh_origin_room_display(origin_session: ClientSession, outbound: dict | list[dict], to_room_id: str) -> None:
    destination_room = get_room(to_room_id)
    if destination_room is None:
        return

    refreshed_display = display_room(origin_session, destination_room)
    refreshed_payload = refreshed_display.get("payload") if isinstance(refreshed_display, dict) else None
    if not isinstance(refreshed_payload, dict):
        return

    refreshed_lines = refreshed_payload.get("lines")
    refreshed_prompt_lines = refreshed_payload.get("prompt_lines")
    messages = outbound if isinstance(outbound, list) else [outbound]
    for message in messages:
        if not isinstance(message, dict) or message.get("type") != "display":
            continue
        payload = message.get("payload")
        if not isinstance(payload, dict):
            continue
        movement = payload.get("movement")
        if not isinstance(movement, dict):
            continue
        if str(movement.get("to_room_id", "")).strip() != str(to_room_id).strip():
            continue

        if isinstance(refreshed_lines, list):
            payload["lines"] = json.loads(json.dumps(refreshed_lines))
        if isinstance(refreshed_prompt_lines, list):
            payload["prompt_lines"] = json.loads(json.dumps(refreshed_prompt_lines))
        break


def _resolve_follow_leader_name(follower_session: ClientSession) -> str:
    normalized_key = (follower_session.following_player_key or "").strip().lower()
    if normalized_key:
        for candidate in connected_clients.values():
            if not candidate.is_connected or candidate.disconnected_by_server or not candidate.is_authenticated:
                continue
            candidate_key = (candidate.player_state_key or candidate.client_id).strip().lower()
            if candidate_key == normalized_key:
                return candidate.authenticated_character_name.strip() or "someone"
    return follower_session.following_player_name.strip() or "someone"


def _collect_followers_for_leader(leader_session: ClientSession, room_id: str) -> list[ClientSession]:
    origin_room_id = str(room_id).strip()
    if not origin_room_id:
        return []

    leader_key = (leader_session.player_state_key or leader_session.client_id).strip().lower()
    if not leader_key:
        return []

    followers: list[ClientSession] = []
    pending_keys = [leader_key]
    seen_keys = {leader_key}
    seen_clients = {leader_session.client_id}

    while pending_keys:
        current_leader_key = pending_keys.pop(0)
        for candidate in connected_clients.values():
            if candidate.client_id in seen_clients:
                continue
            if not candidate.is_connected or candidate.disconnected_by_server or not candidate.is_authenticated:
                continue
            if candidate.player.current_room_id != origin_room_id:
                continue
            if (candidate.following_player_key or "").strip().lower() != current_leader_key:
                continue

            followers.append(candidate)
            seen_clients.add(candidate.client_id)

            candidate_key = (candidate.player_state_key or candidate.client_id).strip().lower()
            if candidate_key and candidate_key not in seen_keys:
                pending_keys.append(candidate_key)
                seen_keys.add(candidate_key)

    return followers


async def _send_room_notice(
    room_id: str,
    parts: list[dict],
    send_outbound_fn,
    *,
    exclude_client_ids: set[str] | None = None,
) -> None:
    for peer in _iter_room_sessions(room_id, exclude_client_ids=exclude_client_ids):
        prompt_parts = [newline_part(2), *build_prompt_parts(peer)]
        message = build_display(
            parts,
            prompt_after=True,
            prompt_parts=prompt_parts,
        )
        await send_outbound_fn(peer.websocket, message)


async def _handle_movement_side_effects(origin_session: ClientSession, outbound: dict | list[dict], send_outbound_fn) -> None:
    actor_name = origin_session.authenticated_character_name.strip() or "Someone"

    for movement in _extract_movement_events(outbound):
        from_room_id = str(movement.get("from_room_id", "")).strip()
        to_room_id = str(movement.get("to_room_id", "")).strip()
        direction = str(movement.get("direction", "")).strip().lower()
        action = str(movement.get("action", "leaves")).strip().lower() or "leaves"
        allow_followers = bool(movement.get("allow_followers", False))
        if not from_room_id or not to_room_id or not direction:
            continue

        grouped_followers = _collect_followers_for_leader(origin_session, from_room_id) if allow_followers else []
        moving_followers = [follower for follower in grouped_followers if not follower.combat.engaged_entity_ids]
        moving_group_ids = {origin_session.client_id, *(follower.client_id for follower in moving_followers)}

        await _send_room_notice(
            from_room_id,
            [
                build_part(actor_name, "bright_cyan", True),
                build_part(f" {action} ", "bright_white"),
                build_part(direction, "bright_yellow", True),
                build_part(".", "bright_white"),
            ],
            send_outbound_fn,
            exclude_client_ids=moving_group_ids,
        )

        for follower in grouped_followers:
            if follower in moving_followers:
                continue

            leader_name = _resolve_follow_leader_name(follower)
            follower.following_player_key = ""
            follower.following_player_name = ""
            await send_outbound_fn(
                follower.websocket,
                build_display(
                    [
                        build_part("Combat keeps you from following ", "bright_white"),
                        build_part(leader_name, "bright_cyan", True),
                        build_part(".", "bright_white"),
                    ],
                    prompt_after=True,
                    prompt_parts=[newline_part(2), *build_prompt_parts(follower)],
                ),
            )

        arrival_direction = DIRECTION_OPPOSITES.get(direction, direction)
        arrival_origin = _format_arrival_origin(arrival_direction)
        await _send_room_notice(
            to_room_id,
            [
                build_part(actor_name, "bright_cyan", True),
                build_part(" arrives from ", "bright_white"),
                build_part(arrival_origin, "bright_yellow", True),
                build_part(".", "bright_white"),
            ],
            send_outbound_fn,
            exclude_client_ids=moving_group_ids,
        )

        entry_messages = get_room_enter_communications(origin_session, to_room_id, apply_state=True)
        entry_lines = _message_lines(entry_messages, audience_filter={"private", "both"})
        if entry_lines:
            insert_room_communication_lines(outbound, entry_lines)
        for entry in entry_messages:
            audience = str(entry.get("audience", "both")).strip().lower() or "both"
            if audience not in {"room", "both"}:
                continue
            message = str(entry.get("message", "")).strip()
            if not message:
                continue
            await _send_room_notice(
                to_room_id,
                [build_part(message, "bright_white")],
                send_outbound_fn,
                exclude_client_ids=moving_group_ids,
            )

        destination_room = get_room(to_room_id)
        for follower in moving_followers:
            leader_name = _resolve_follow_leader_name(follower)
            follower.following_player_name = leader_name
            follower.player.current_room_id = to_room_id

            await _send_room_notice(
                from_room_id,
                [
                    build_part(follower.authenticated_character_name.strip() or "Someone", "bright_cyan", True),
                    build_part(" leaves ", "bright_white"),
                    build_part(direction, "bright_yellow", True),
                    build_part(", following ", "bright_white"),
                    build_part(leader_name, "bright_cyan", True),
                    build_part(".", "bright_white"),
                ],
                send_outbound_fn,
                exclude_client_ids=moving_group_ids,
            )

            await _send_room_notice(
                to_room_id,
                [
                    build_part(follower.authenticated_character_name.strip() or "Someone", "bright_cyan", True),
                    build_part(" arrives from ", "bright_white"),
                    build_part(arrival_origin, "bright_yellow", True),
                    build_part(", following ", "bright_white"),
                    build_part(leader_name, "bright_cyan", True),
                    build_part(".", "bright_white"),
                ],
                send_outbound_fn,
                exclude_client_ids=moving_group_ids,
            )

            if destination_room is None:
                follow_display = display_error(f"Destination room not found: {to_room_id}", follower)
            else:
                maybe_auto_engage_current_room(follower)
                follow_display = display_room(follower, destination_room)

            follow_prefix_lines = [
                build_line(
                    build_part("You follow ", "bright_white"),
                    build_part(leader_name, "bright_cyan", True),
                    build_part(" ", "bright_white"),
                    build_part(direction, "bright_yellow", True),
                    build_part(".", "bright_white"),
                ),
                [],
            ]
            follow_entry_messages = get_room_enter_communications(follower, to_room_id, apply_state=True)
            follow_entry_lines = _message_lines(follow_entry_messages, audience_filter={"private", "both"})
            _prepend_display_lines(follow_display, follow_prefix_lines)
            if follow_entry_lines:
                insert_room_communication_lines(follow_display, follow_entry_lines)
            for entry in follow_entry_messages:
                audience = str(entry.get("audience", "both")).strip().lower() or "both"
                if audience not in {"room", "both"}:
                    continue
                message = str(entry.get("message", "")).strip()
                if not message:
                    continue
                await _send_room_notice(
                    to_room_id,
                    [build_part(message, "bright_white")],
                    send_outbound_fn,
                    exclude_client_ids=moving_group_ids,
                )
            await send_outbound_fn(follower.websocket, follow_display)

        _refresh_origin_room_display(origin_session, outbound, to_room_id)
        if entry_lines:
            insert_room_communication_lines(outbound, entry_lines)
