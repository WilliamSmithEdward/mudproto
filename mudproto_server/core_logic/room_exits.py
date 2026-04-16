"""Configurable room-exit state and open/close handling helpers."""

import re

from display_core import build_part, newline_part
from inventory import consume_item_on_use, get_item_keywords, item_unlocks_lock
from models import ClientSession
from settings import DIRECTION_ALIASES, DIRECTION_SHORT_LABELS
from world import Room, get_room


_VALID_DIRECTIONS = {"north", "south", "east", "west", "up", "down"}
_REVERSE_DIRECTIONS = {
    "north": "south",
    "south": "north",
    "east": "west",
    "west": "east",
    "up": "down",
    "down": "up",
}


def normalize_direction_token(text: str) -> str:
    normalized = str(text).strip().lower()
    return DIRECTION_ALIASES.get(normalized, normalized)


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


def _definite_exit_label(exit_detail: dict, *, include_direction: bool = True) -> str:
    exit_label = _exit_label(exit_detail, include_direction=include_direction).strip()
    if not exit_label:
        return "the exit"
    if exit_label.lower().startswith(("the ", "a ", "an ")):
        return exit_label
    return f"the {exit_label}"


def _default_exit_message(exit_detail: dict, message_kind: str) -> str:
    exit_type = str(exit_detail.get("exit_type", "exit")).strip().lower() or "exit"
    exit_label = _definite_exit_label(exit_detail)

    if message_kind == "open":
        if exit_type in {"gate", "hatch", "trapdoor"}:
            return f"You pull {exit_label} open."
        if exit_type in {"door", "portcullis"}:
            return f"You swing {exit_label} open."
        return f"You open {exit_label}."

    if message_kind == "close":
        if exit_type in {"gate", "door", "portcullis"}:
            return f"You swing {exit_label} shut."
        if exit_type in {"hatch", "trapdoor"}:
            return f"You pull {exit_label} shut."
        return f"You close {exit_label}."

    if message_kind == "lock":
        return f"You lock {exit_label}."
    if message_kind == "unlock":
        return f"You unlock {exit_label}."
    if message_kind == "closed":
        return f"{exit_label.capitalize()} is closed."
    if message_kind == "locked":
        return f"{exit_label.capitalize()} is locked."
    if message_kind == "needs_key":
        return f"You do not have the proper key for {exit_label}."
    if message_kind == "must_close_to_lock":
        return f"{exit_label.capitalize()} must be closed before it can be locked."
    if message_kind == "already_open":
        return f"{exit_label.capitalize()} is already open."
    if message_kind == "already_closed":
        return f"{exit_label.capitalize()} is already closed."
    if message_kind == "already_locked":
        return f"{exit_label.capitalize()} is already locked."
    if message_kind == "already_unlocked":
        return f"{exit_label.capitalize()} is already unlocked."
    return exit_label.capitalize()


def _sync_linked_exit_state(room: Room, exit_detail: dict) -> None:
    direction = normalize_direction_token(exit_detail.get("direction", ""))
    reverse_direction = _REVERSE_DIRECTIONS.get(direction)
    destination_room_id = room.exits.get(direction)
    if not reverse_direction or not destination_room_id:
        return

    destination_room = get_room(destination_room_id)
    if destination_room is None:
        return
    if destination_room.exits.get(reverse_direction) != room.room_id:
        return

    reverse_exit_detail = get_exit_detail(destination_room, reverse_direction)
    if reverse_exit_detail is None:
        return

    reverse_exit_detail["is_closed"] = bool(exit_detail.get("is_closed", False))
    reverse_exit_detail["is_locked"] = bool(exit_detail.get("is_locked", False))


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
        closed_message = str(exit_detail.get("closed_message", "")).strip()
        return False, closed_message or _default_exit_message(exit_detail, "closed")

    if bool(exit_detail.get("is_closed", False)):
        closed_message = str(exit_detail.get("closed_message", "")).strip()
        return False, closed_message or _default_exit_message(exit_detail, "closed")

    return True, None


def format_prompt_exit_token(room: Room, direction: str) -> str:
    normalized_direction = normalize_direction_token(direction)
    letter = DIRECTION_SHORT_LABELS.get(normalized_direction, normalized_direction[:1].upper() or "?")
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


def _split_selector_and_key(selector_text: str) -> tuple[str, str | None]:
    cleaned = " ".join(str(selector_text).strip().split())
    if not cleaned:
        return "", None

    parts = re.split(r"\s+with\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip() or None
    return cleaned, None


def _find_matching_key_item(session: ClientSession, lock_id: str, key_selector: str | None = None):
    normalized_lock_id = str(lock_id).strip().lower()
    if not normalized_lock_id:
        return None

    selector_tokens = [token.lower() for token in re.findall(r"[a-zA-Z0-9]+", key_selector or "")]
    candidate_items = list(session.inventory_items.values())
    candidate_items.sort(key=lambda item: (item.name.lower(), item.item_id))

    for item in candidate_items:
        if not item_unlocks_lock(item, normalized_lock_id):
            continue
        if selector_tokens and not all(token in get_item_keywords(item) for token in selector_tokens):
            continue
        return item

    return None


def handle_room_exit_command(
    session: ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> dict | None:
    normalized_verb = str(verb).strip().lower()
    if normalized_verb not in {"open", "ope", "op", "close", "clos", "clo", "cl", "lock", "unlock", "unl", "unlo", "unloc"}:
        return None

    from display_feedback import display_command_result, display_error

    if not args:
        return display_error(f"Usage: {normalized_verb} <gate|door|direction>", session)

    room = get_room(session.player.current_room_id)
    if room is None:
        return display_error(f"Current room not found: {session.player.current_room_id}", session)

    selector_text = " ".join(args).strip()
    key_selector: str | None = None
    if normalized_verb in {"lock", "unlock", "unl", "unlo", "unloc"}:
        selector_text, key_selector = _split_selector_and_key(selector_text)

    exit_detail = resolve_room_exit_selector(room, selector_text)
    if exit_detail is None:
        return None

    can_close = bool(exit_detail.get("can_close", True))
    can_lock = bool(exit_detail.get("can_lock", bool(str(exit_detail.get("lock_id", "")).strip())))
    lock_id = str(exit_detail.get("lock_id", "")).strip().lower()
    exit_label = _exit_label(exit_detail)

    if normalized_verb in {"open", "ope", "op", "close", "clos", "clo", "cl"} and not can_close:
        return display_command_result(session, [
            build_part(f"The {exit_label} cannot be opened or closed.", "feedback.text"),
        ])

    if normalized_verb in {"open", "ope", "op"}:
        if bool(exit_detail.get("is_locked", False)):
            locked_message = str(exit_detail.get("locked_message", "")).strip()
            return display_command_result(session, [
                build_part(locked_message or _default_exit_message(exit_detail, "locked"), "feedback.text"),
            ])
        if not bool(exit_detail.get("is_closed", False)):
            already_open_message = str(exit_detail.get("already_open_message", "")).strip()
            return display_command_result(session, [
                build_part(already_open_message or _default_exit_message(exit_detail, "already_open"), "feedback.text"),
            ])

        exit_detail["is_closed"] = False
        _sync_linked_exit_state(room, exit_detail)
        open_message = str(exit_detail.get("open_message", "")).strip()
        return display_command_result(session, [
            build_part(open_message or _default_exit_message(exit_detail, "open"), "feedback.text"),
        ])

    if normalized_verb in {"close", "clos", "clo", "cl"}:
        if bool(exit_detail.get("is_closed", False)):
            already_closed_message = str(exit_detail.get("already_closed_message", "")).strip()
            return display_command_result(session, [
                build_part(already_closed_message or _default_exit_message(exit_detail, "already_closed"), "feedback.text"),
            ])

        exit_detail["is_closed"] = True
        _sync_linked_exit_state(room, exit_detail)
        close_message = str(exit_detail.get("close_message", "")).strip()
        return display_command_result(session, [
            build_part(close_message or _default_exit_message(exit_detail, "close"), "feedback.text"),
        ])

    if not can_lock or not lock_id:
        return display_command_result(session, [
            build_part(f"The {exit_label} cannot be locked or unlocked.", "feedback.text"),
        ])

    if normalized_verb in {"unlock", "unl", "unlo", "unloc"}:
        if not bool(exit_detail.get("is_locked", False)):
            already_unlocked_message = str(exit_detail.get("already_unlocked_message", "")).strip()
            return display_command_result(session, [
                build_part(already_unlocked_message or _default_exit_message(exit_detail, "already_unlocked"), "feedback.text"),
            ])

        key_item = _find_matching_key_item(session, lock_id, key_selector)
        if key_item is None:
            needs_key_message = str(exit_detail.get("needs_key_message", "")).strip()
            return display_command_result(session, [
                build_part(needs_key_message or _default_exit_message(exit_detail, "needs_key"), "feedback.text"),
            ])

        exit_detail["is_locked"] = False
        _sync_linked_exit_state(room, exit_detail)
        unlock_message = str(exit_detail.get("unlock_message", "")).strip()
        parts = [
            build_part(unlock_message or _default_exit_message(exit_detail, "unlock"), "feedback.text"),
        ]
        consume_message = consume_item_on_use(session, key_item)
        if consume_message:
            parts.extend([
                newline_part(),
                build_part(consume_message, "feedback.text"),
            ])
        return display_command_result(session, parts)

    if bool(exit_detail.get("is_locked", False)):
        already_locked_message = str(exit_detail.get("already_locked_message", "")).strip()
        return display_command_result(session, [
            build_part(already_locked_message or _default_exit_message(exit_detail, "already_locked"), "feedback.text"),
        ])

    if not bool(exit_detail.get("is_closed", False)):
        must_close_message = str(exit_detail.get("must_close_to_lock_message", "")).strip()
        return display_command_result(session, [
            build_part(must_close_message or _default_exit_message(exit_detail, "must_close_to_lock"), "feedback.text"),
        ])

    key_item = _find_matching_key_item(session, lock_id, key_selector)
    if key_item is None:
        needs_key_message = str(exit_detail.get("needs_key_message", "")).strip()
        return display_command_result(session, [
            build_part(needs_key_message or _default_exit_message(exit_detail, "needs_key"), "feedback.text"),
        ])

    exit_detail["is_locked"] = True
    _sync_linked_exit_state(room, exit_detail)
    lock_message = str(exit_detail.get("lock_message", "")).strip()
    parts = [
        build_part(lock_message or _default_exit_message(exit_detail, "lock"), "feedback.text"),
    ]
    consume_message = consume_item_on_use(session, key_item)
    if consume_message:
        parts.extend([
            newline_part(),
            build_part(consume_message, "feedback.text"),
        ])
    return display_command_result(session, parts)
