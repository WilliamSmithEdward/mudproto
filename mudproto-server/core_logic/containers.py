from __future__ import annotations

"""Generic container helpers for item containers and corpses."""

import re
from typing import Literal

from display_core import build_menu_table_parts, build_part
from display_feedback import display_command_result, display_error
from grammar import with_article
from inventory import get_item_keywords, hydrate_misc_item_from_template, parse_item_selector
from item_logic import _build_corpse_label, _build_item_reference_parts, _item_highlight_color
from models import ClientSession, CorpseState, ItemState
from targeting_entities import list_room_corpses, resolve_room_corpse_selector
from targeting_items import _list_room_ground_items, _resolve_inventory_selector


ContainerLocation = Literal["room", "inventory", "corpse"]
ContainerTarget = CorpseState | ItemState


def is_item_container(item: ItemState) -> bool:
    hydrate_misc_item_from_template(item)
    return str(getattr(item, "item_type", "misc")).strip().lower() == "container"


def can_pick_up_item(item: ItemState) -> tuple[bool, str | None]:
    if not is_item_container(item):
        return True, None
    if bool(getattr(item, "portable", True)):
        return True, None
    return False, f"The {item.name.strip() or 'container'} is fixed in place."


def _container_label(container: ContainerTarget) -> str:
    if isinstance(container, CorpseState):
        return _build_corpse_label(container.source_name)
    return str(getattr(container, "name", "container")).strip() or "container"


def _container_reference_text(container: ContainerTarget) -> str:
    label = _container_label(container)
    if isinstance(container, CorpseState):
        return label
    return with_article(label)


def _container_item_map(container: ContainerTarget) -> dict[str, ItemState]:
    if isinstance(container, CorpseState):
        return container.loot_items
    return container.container_items


def _container_coin_amount(container: ContainerTarget) -> int:
    if isinstance(container, CorpseState):
        return max(0, int(container.coins))
    return 0


def _normalize_container_selector(selector_text: str) -> str:
    cleaned = " ".join(str(selector_text).strip().split())
    lowered = cleaned.lower()

    for prefix in ("from the ", "from ", "inside the ", "inside ", "into the ", "into "):
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            lowered = cleaned.lower()
            break

    for suffix in (" in the room", " in room", " on the ground", " on ground", " here"):
        if lowered.endswith(suffix):
            cleaned = cleaned[:-len(suffix)].strip()
            lowered = cleaned.lower()
            break

    return cleaned


def resolve_accessible_container(
    session: ClientSession,
    selector_text: str,
) -> tuple[ContainerTarget | None, ContainerLocation | None, str | None]:
    normalized = _normalize_container_selector(selector_text)
    if not normalized:
        return None, None, "Provide a container selector."

    corpse, _ = resolve_room_corpse_selector(session, session.player.current_room_id, normalized)
    if corpse is not None:
        return corpse, "corpse", None

    requested_index, keywords, parse_error = parse_item_selector(normalized)
    if parse_error is not None:
        return None, None, parse_error

    candidates: list[tuple[int, ContainerLocation, ItemState]] = []
    for item in session.inventory_items.values():
        if is_item_container(item):
            candidates.append((0, "inventory", item))
    for item in _list_room_ground_items(session, session.player.current_room_id):
        if is_item_container(item):
            candidates.append((1, "room", item))

    candidates.sort(key=lambda entry: (entry[0], entry[2].name.lower(), entry[2].item_id))

    matches: list[tuple[ContainerLocation, ItemState]] = []
    for _, location, item in candidates:
        item_keywords = get_item_keywords(item)
        if all(keyword in item_keywords for keyword in keywords):
            matches.append((location, item))

    if not matches:
        return None, None, f"No container matching '{selector_text}' is here."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, None, f"Only {len(matches)} container match(es) found for '{selector_text}'."
        location, container = matches[requested_index - 1]
        return container, location, None

    location, container = matches[0]
    return container, location, None


def split_item_and_container_selectors(
    session: ClientSession,
    args: list[str],
) -> tuple[str | None, str | None, str | None]:
    cleaned_args = [arg.strip() for arg in args if arg.strip()]
    if len(cleaned_args) < 2:
        return None, None, "Usage: <item> <container>"

    lowered = [arg.lower() for arg in cleaned_args]
    for separator in ("into", "inside", "from", "in"):
        if separator in lowered:
            split_index = lowered.index(separator)
            item_selector = " ".join(cleaned_args[:split_index]).strip()
            container_selector = " ".join(cleaned_args[split_index + 1:]).strip()
            if item_selector and container_selector:
                container, _, _ = resolve_accessible_container(session, container_selector)
                if container is not None:
                    return item_selector, container_selector, None

    for split_index in range(1, len(cleaned_args)):
        item_selector = " ".join(cleaned_args[:split_index]).strip()
        container_selector = " ".join(cleaned_args[split_index:]).strip()
        container, _, _ = resolve_accessible_container(session, container_selector)
        if item_selector and container is not None:
            return item_selector, container_selector, None

    item_selector = " ".join(cleaned_args[:-1]).strip()
    container_selector = cleaned_args[-1].strip()
    if item_selector and container_selector:
        return item_selector, container_selector, None

    return None, None, "Usage: <item> <container>"


def display_container_examination(
    session: ClientSession,
    container: ContainerTarget,
    *,
    default_location: str | None = None,
):
    title = _container_label(container)
    rows: list[list[str]] = []
    row_cell_colors: list[list[str]] = []

    if isinstance(container, CorpseState):
        rows.append(["Type", "Corpse"])
        row_cell_colors.append(["bright_cyan", "bright_yellow"])
    else:
        rows.append(["Type", "Container"])
        row_cell_colors.append(["bright_cyan", "bright_yellow"])
        rows.append(["Location", str(default_location or "Room")])
        row_cell_colors.append(["bright_cyan", "bright_white"])
        rows.append(["Carryable", "Yes" if bool(getattr(container, "portable", True)) else "No"])
        row_cell_colors.append(["bright_cyan", "bright_white"])

    rows.append(["Coins", str(_container_coin_amount(container))])
    row_cell_colors.append(["bright_cyan", "bright_cyan"])

    container_items = list(_container_item_map(container).values())
    container_items.sort(key=lambda item: item.name.lower())
    if container_items:
        item_counts: dict[str, int] = {}
        item_names: dict[str, str] = {}
        item_colors: dict[str, str] = {}
        item_order: list[str] = []

        for contained_item in container_items:
            normalized_name = contained_item.name.strip().lower()
            if not normalized_name:
                continue
            if normalized_name not in item_counts:
                item_counts[normalized_name] = 0
                item_names[normalized_name] = contained_item.name
                item_colors[normalized_name] = _item_highlight_color(contained_item)
                item_order.append(normalized_name)
            item_counts[normalized_name] += 1

        for item_key in item_order:
            count = item_counts[item_key]
            item_label = item_names[item_key] if count == 1 else f"{item_names[item_key]} [{count}]"
            rows.append(["Item", item_label])
            row_cell_colors.append(["bright_magenta", item_colors[item_key]])
    else:
        rows.append(["Items", "None"])
        row_cell_colors.append(["bright_magenta", "bright_black"])

    parts = build_menu_table_parts(
        title,
        ["Loot", "Contents"],
        rows,
        column_colors=["bright_cyan", "bright_white"],
        row_cell_colors=row_cell_colors,
        column_alignments=["left", "left"],
    )

    if not isinstance(container, CorpseState):
        description = str(getattr(container, "description", "")).strip()
        if description:
            parts.extend([
                build_part("\n"),
                build_part("Description", "bright_white", True),
                build_part("\n"),
                build_part(description, "bright_white"),
            ])

    return display_command_result(session, parts)


def take_all_from_container(session: ClientSession, container: ContainerTarget):
    item_map = _container_item_map(container)
    taken_items = list(item_map.values())
    taken_items.sort(key=lambda item: item.name.lower())
    taken_coins = _container_coin_amount(container)

    if not taken_items and taken_coins <= 0:
        return display_error(f"{_container_label(container).title()} is empty.", session)

    if isinstance(container, CorpseState):
        container.coins = 0
    if taken_coins > 0:
        session.status.coins += taken_coins

    for item in taken_items:
        session.inventory_items[item.item_id] = item
        item_map.pop(item.item_id, None)

    parts = [
        build_part("You take everything from ", "bright_white"),
        build_part(_container_reference_text(container), "bright_yellow", True),
        build_part(".", "bright_white"),
    ]
    if taken_coins > 0:
        parts.extend([
            build_part("\n"),
            build_part("Coins +", "bright_white"),
            build_part(str(taken_coins), "bright_cyan", True),
        ])
    for item in taken_items:
        parts.extend([
            build_part("\n"),
            build_part("You take ", "bright_white"),
            *_build_item_reference_parts(item),
            build_part(".", "bright_white"),
        ])

    return display_command_result(session, parts)


def take_item_from_container(session: ClientSession, container: ContainerTarget, item_selector: str):
    normalized = str(item_selector).strip().lower()
    if normalized == "all":
        return take_all_from_container(session, container)
    if normalized in {"coin", "coins"}:
        taken_coins = _container_coin_amount(container)
        if taken_coins <= 0:
            return display_error(f"{_container_label(container).title()} has no coins to take.", session)
        if isinstance(container, CorpseState):
            container.coins = 0
        session.status.coins += taken_coins
        return display_command_result(session, [
            build_part("You take ", "bright_white"),
            build_part(str(taken_coins), "bright_cyan", True),
            build_part(" coins from ", "bright_white"),
            build_part(_container_reference_text(container), "bright_yellow", True),
            build_part(".", "bright_white"),
        ])

    requested_index, keywords, parse_error = parse_item_selector(item_selector)
    if parse_error is not None:
        return display_error(parse_error, session)

    container_items = list(_container_item_map(container).values())
    container_items.sort(key=lambda item: (item.name.lower(), item.item_id))
    matches = [item for item in container_items if all(keyword in get_item_keywords(item) for keyword in keywords)]
    if not matches:
        return display_error(f"No item matching '{item_selector}' is in {_container_label(container)}.", session)

    selected_item = matches[0]
    if requested_index is not None:
        if requested_index > len(matches):
            return display_error(f"Only {len(matches)} match(es) found for '{item_selector}'.", session)
        selected_item = matches[requested_index - 1]

    _container_item_map(container).pop(selected_item.item_id, None)
    session.inventory_items[selected_item.item_id] = selected_item
    return display_command_result(session, [
        build_part("You take ", "bright_white"),
        *_build_item_reference_parts(selected_item),
        build_part(" from ", "bright_white"),
        build_part(_container_reference_text(container), "bright_yellow", True),
        build_part(".", "bright_white"),
    ])


def put_item_into_container(session: ClientSession, item_selector: str, container: ContainerTarget):
    item, resolve_error = _resolve_inventory_selector(session, item_selector)
    if item is None:
        return display_error(resolve_error or f"No inventory item matches '{item_selector}'.", session)

    if isinstance(container, ItemState) and item.item_id == container.item_id:
        return display_error("You cannot put a container inside itself.", session)

    session.inventory_items.pop(item.item_id, None)
    _container_item_map(container)[item.item_id] = item
    return display_command_result(session, [
        build_part("You place ", "bright_white"),
        *_build_item_reference_parts(item),
        build_part(" into ", "bright_white"),
        build_part(_container_reference_text(container), "bright_yellow", True),
        build_part(".", "bright_white"),
    ])
