"""Configurable room-exit state and open/close handling helpers."""

import re

from display_core import build_part
from models import ClientSession
from world import Room, get_room


_VALID_DIRECTIONS = {"north", "south", "east", "west", "up", "down"}
_DIRECTION_ALIASES = {
    "n": "north",
    "no": "north",
    "nor": "north",
    "nort": "north",
    "s": "south",
    "so": "south",
    "sou": "south",
    "sout": "south",
    "e": "east",
    "ea": "east",
    "eas": "east",
    "w": "west",
    "we": "west",
    "wes": "west",
    "u": "up",
    "d": "down",
    "do": "down",
    "dow": "down",
}
_DIRECTION_LETTERS = {
    "north": "N",
    "south": "S",
    "east": "E",
    "west": "W",
    "up": "U",
    "down": "D",
}


def normalize_direction_token(text: str) -> str:
    normalized = str(text).strip().lower()
    return _DIRECTION_ALIASES.get(normalized, normalized)


def _get_exit_details(room: Room) -> list[dict]:
    return room.exit_details if isinstance(room.exit_details, list) else []


def get_exit_detail(room: Room, direction: str) -> dict | None:
    normalized_direction = normalize_direction_token(direction)
    for exit_detail in _get_exit_details(room):
        if normalize_direction_token(exit_detail.get("direction", "")) == normalized_direction:
            return exit_detail
    return None


def _exit_label(exit_detail: dict, *, include_direction: bool = False) -> str:
    exit_name = str(exit_detail.get("name", "")).strip()
    if exit_name:
        return exit_name

    exit_type = str(exit_detail.get("exit_type", "exit")).strip().lower() or "exit"
    direction = normalize_direction_token(exit_detail.get("direction", ""))
    if include_direction and direction in _VALID_DIRECTIONS:
        return f"{exit_type} to the {direction}"
    return exit_type


def is_exit_closed(room: Room, direction: str) -> bool:
    exit_detail = get_exit_detail(room, direction)
    return bool(exit_detail and exit_detail.get("is_closed", False))


def is_exit_locked(room: Room, direction: str) -> bool:
    exit_detail = get_exit_detail(room, direction)
    return bool(exit_detail and exit_detail.get("is_locked", False))


def can_traverse_exit(room: Room, direction: str) -> tuple[bool, str | None]:
    exit_detail = get_exit_detail(room, direction)
    if exit_detail is None:
        return True, None

    if bool(exit_detail.get("is_locked", False)):
        locked_message = str(exit_detail.get("locked_message", "")).strip()
        return False, locked_message or f"The {_exit_label(exit_detail, include_direction=True)} is locked."

    if bool(exit_detail.get("is_closed", False)):
        closed_message = str(exit_detail.get("closed_message", "")).strip()
        return False, closed_message or f"The {_exit_label(exit_detail, include_direction=True)} is closed."

    return True, None


def format_prompt_exit_token(room: Room, direction: str) -> str:
    normalized_direction = normalize_direction_token(direction)
    letter = _DIRECTION_LETTERS.get(normalized_direction, normalized_direction[:1].upper() or "?")
    if is_exit_closed(room, normalized_direction):
        return f"({letter})"
    return letter


def describe_exit_status(room: Room, direction: str) -> str:
    exit_detail = get_exit_detail(room, direction)
    if exit_detail is None:
        return ""

    status_parts: list[str] = []
    if bool(exit_detail.get("is_locked", False)):
        status_parts.append("locked")
    elif bool(exit_detail.get("is_closed", False)):
        status_parts.append("closed")

    exit_type = str(exit_detail.get("exit_type", "")).strip().lower()
    if exit_type:
        status_parts.append(exit_type)

    if not status_parts:
        return ""
    return f" ({', '.join(status_parts)})"


def _exit_keywords(exit_detail: dict) -> set[str]:
    keywords: set[str] = set()
    for source in (
        exit_detail.get("exit_type", ""),
        exit_detail.get("name", ""),
        exit_detail.get("direction", ""),
    ):
        keywords.update(token.lower() for token in re.findall(r"[a-zA-Z0-9]+", str(source)))

    raw_keywords = exit_detail.get("keywords", [])
    if isinstance(raw_keywords, list):
        for keyword in raw_keywords:
            keywords.update(token.lower() for token in re.findall(r"[a-zA-Z0-9]+", str(keyword)))

    return {keyword for keyword in keywords if keyword}


def resolve_room_exit_selector(room: Room, selector_text: str) -> dict | None:
    selector_tokens = [token.lower() for token in re.findall(r"[a-zA-Z0-9]+", selector_text)]
    direction_hint: str | None = None
    filtered_tokens: list[str] = []

    for token in selector_tokens:
        normalized_direction = normalize_direction_token(token)
        if normalized_direction in _VALID_DIRECTIONS:
            direction_hint = normalized_direction
        else:
            filtered_tokens.append(token)

    candidates: list[dict] = []
    for exit_detail in _get_exit_details(room):
        direction = normalize_direction_token(exit_detail.get("direction", ""))
        if direction not in room.exits:
            continue
        if direction_hint is not None and direction != direction_hint:
            continue

        keywords = _exit_keywords(exit_detail)
        if filtered_tokens and not all(token in keywords for token in filtered_tokens):
            continue
        candidates.append(exit_detail)

    if not candidates:
        return None

    return candidates[0]


def handle_room_exit_command(
    session: ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> dict | None:
    normalized_verb = str(verb).strip().lower()
    if normalized_verb not in {"open", "ope", "op", "close", "clos", "clo", "cl"}:
        return None

    from display_feedback import display_command_result, display_error

    if not args:
        return display_error(f"Usage: {normalized_verb} <gate|door|direction>", session)

    room = get_room(session.player.current_room_id)
    if room is None:
        return display_error(f"Current room not found: {session.player.current_room_id}", session)

    selector_text = " ".join(args).strip()
    exit_detail = resolve_room_exit_selector(room, selector_text)
    if exit_detail is None:
        return None

    can_close = bool(exit_detail.get("can_close", True))
    exit_label = _exit_label(exit_detail)

    if not can_close:
        return display_error(f"The {exit_label} cannot be opened or closed.", session)

    if normalized_verb in {"open", "ope", "op"}:
        if bool(exit_detail.get("is_locked", False)):
            locked_message = str(exit_detail.get("locked_message", "")).strip()
            return display_error(locked_message or f"The {exit_label} is locked.", session)
        if not bool(exit_detail.get("is_closed", False)):
            already_open_message = str(exit_detail.get("already_open_message", "")).strip()
            return display_command_result(session, [
                build_part(already_open_message or f"The {exit_label} is already open.", "bright_white"),
            ])

        exit_detail["is_closed"] = False
        open_message = str(exit_detail.get("open_message", "")).strip()
        return display_command_result(session, [
            build_part(open_message or f"You open the {exit_label}.", "bright_white"),
        ])

    if bool(exit_detail.get("is_closed", False)):
        already_closed_message = str(exit_detail.get("already_closed_message", "")).strip()
        return display_command_result(session, [
            build_part(already_closed_message or f"The {exit_label} is already closed.", "bright_white"),
        ])

    exit_detail["is_closed"] = True
    close_message = str(exit_detail.get("close_message", "")).strip()
    return display_command_result(session, [
        build_part(close_message or f"You close the {exit_label}.", "bright_white"),
    ])
