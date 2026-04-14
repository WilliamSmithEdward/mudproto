"""Configurable room-object resolution and examination helpers."""

import re

from display_core import build_part
from display_feedback import display_command_result
from inventory import parse_item_selector
from models import ClientSession
from world import Room


def _room_object_keywords(room_object: dict) -> set[str]:
    keywords: set[str] = set()

    for source in (room_object.get("object_id", ""), room_object.get("name", "")):
        keywords.update(token.lower() for token in re.findall(r"[a-zA-Z0-9]+", str(source)))

    raw_keywords = room_object.get("keywords", [])
    if isinstance(raw_keywords, list):
        for keyword in raw_keywords:
            keywords.update(token.lower() for token in re.findall(r"[a-zA-Z0-9]+", str(keyword)))

    return {keyword for keyword in keywords if keyword}


def resolve_room_object_selector(room: Room, selector: str) -> tuple[dict | None, str | None]:
    requested_index, keywords, parse_error = parse_item_selector(selector)
    if parse_error is not None:
        return None, parse_error

    matches: list[dict] = []
    for room_object in room.room_objects:
        object_keywords = _room_object_keywords(room_object)
        if all(keyword in object_keywords for keyword in keywords):
            matches.append(room_object)

    matches.sort(
        key=lambda room_object: (
            str(room_object.get("name", "")).strip().lower(),
            str(room_object.get("object_id", "")).strip().lower(),
        )
    )

    if not matches:
        return None, f"No room feature matches '{selector}'."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} room feature(s) match '{selector}'."
        return matches[requested_index - 1], None

    return matches[0], None


def display_room_object_examination(session: ClientSession, room: Room, room_object: dict) -> dict:
    _ = room
    description = str(room_object.get("description", "")).strip() or "Nothing about it stands out."

    return display_command_result(session, [
        build_part(description, "bright_white"),
    ])
