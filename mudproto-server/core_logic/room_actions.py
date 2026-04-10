"""Configurable room keyword interactions and action application."""

from display_core import build_line, build_part
from display_feedback import display_command_result, display_error
from display_room import display_exits, display_room
from models import ClientSession
from world import Room, get_room


_REVEAL_EXIT_ACTIONS = {"set_exit", "reveal_exit", "show_exit"}
_HIDE_EXIT_ACTIONS = {"hide_exit", "remove_exit", "unset_exit"}


def _normalize_keyword_text(text: str) -> str:
    return " ".join(str(text).strip().lower().split())


def _prepend_message(outbound: dict, message: str) -> dict:
    payload = outbound.get("payload") if isinstance(outbound, dict) else None
    if not isinstance(payload, dict):
        return outbound

    lines = payload.get("lines")
    if not isinstance(lines, list):
        return outbound

    payload["lines"] = [
        build_line(build_part(message, "bright_white")),
        [],
    ] + lines
    return outbound


def _apply_keyword_actions(room: Room, keyword_action: dict) -> bool:
    changed = False

    for action in keyword_action.get("actions", []):
        action_type = str(action.get("type", "")).strip().lower()
        direction = str(action.get("direction", "")).strip().lower()
        if not direction:
            continue

        if action_type in _REVEAL_EXIT_ACTIONS:
            destination_room_id = str(action.get("destination_room_id", "")).strip()
            if not destination_room_id:
                continue
            if room.exits.get(direction) != destination_room_id:
                room.exits[direction] = destination_room_id
                changed = True
            continue

        if action_type in _HIDE_EXIT_ACTIONS and direction in room.exits:
            room.exits.pop(direction, None)
            changed = True

    return changed


def _build_room_keyword_outbound(session: ClientSession, room: Room, keyword_action: dict, *, changed: bool) -> dict:
    message = str(keyword_action.get("message", "")).strip()
    already_message = str(keyword_action.get("already_message", "")).strip()
    display_message = message if changed else (already_message or message or "Nothing happens.")

    refresh_view = str(keyword_action.get("refresh_view", "none")).strip().lower() or "none"
    if refresh_view == "none":
        return display_command_result(session, [
            build_part(display_message, "bright_white"),
        ])

    if refresh_view == "room":
        outbound = display_room(session, room)
    else:
        outbound = display_exits(session, room)

    return _prepend_message(outbound, display_message)


def handle_room_keyword_action(session: ClientSession, command_text: str) -> dict | None:
    room = get_room(session.player.current_room_id)
    if room is None:
        return display_error(f"Current room not found: {session.player.current_room_id}", session)

    normalized_command = _normalize_keyword_text(command_text)
    if not normalized_command:
        return None

    for keyword_action in room.keyword_actions:
        keywords = keyword_action.get("keywords", [])
        if not isinstance(keywords, list):
            continue

        if any(_normalize_keyword_text(keyword) == normalized_command for keyword in keywords):
            changed = _apply_keyword_actions(room, keyword_action)
            return _build_room_keyword_outbound(session, room, keyword_action, changed=changed)

    return None
