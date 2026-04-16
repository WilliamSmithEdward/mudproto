from __future__ import annotations

"""Shared container helpers for all container-like objects."""

import re
from textwrap import wrap
from typing import Literal

from display_core import build_menu_table_parts, build_part, newline_part
from display_feedback import display_command_result, display_error
from grammar import with_article
from inventory import consume_item_on_use, get_item_keywords, hydrate_misc_item_from_template, item_unlocks_lock, parse_item_selector
from item_logic import _build_corpse_label, _build_item_reference_parts, _item_highlight_color
from models import ClientSession, CorpseState, ItemState
from targeting_entities import resolve_room_corpse_selector
from targeting_items import _list_room_ground_items, _resolve_inventory_selector


ContainerLocation = Literal["room", "inventory", "corpse"]
ContainerTarget = CorpseState | ItemState

_CONTAINER_DESCRIPTION_COLUMN_WIDTH = 58


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
    return str(getattr(container, "name", "container")).strip() or "container"


def _container_definite_label(container: ContainerTarget) -> str:
    label = _container_label(container).strip() or "container"
    if label.lower().startswith(("the ", "a ", "an ")):
        return label
    return f"the {label}"


def _container_reference_text(container: ContainerTarget) -> str:
    return with_article(_container_label(container))


def _sentence_case(text: str) -> str:
    cleaned = str(text).strip()
    if not cleaned:
        return ""
    return f"{cleaned[:1].upper()}{cleaned[1:]}"


def _default_container_message(container: ContainerTarget, message_kind: str) -> str:
    container_label = _container_definite_label(container)

    if message_kind == "open":
        return f"You open {container_label}."
    if message_kind == "close":
        return f"You close {container_label}."
    if message_kind == "lock":
        return f"You lock {container_label}."
    if message_kind == "unlock":
        return f"You unlock {container_label}."
    if message_kind == "closed":
        return f"{_sentence_case(container_label)} is closed."
    if message_kind == "locked":
        return f"{_sentence_case(container_label)} is locked."
    if message_kind == "needs_key":
        return f"You do not have the proper key for {container_label}."
    if message_kind == "must_close_to_lock":
        return f"{_sentence_case(container_label)} must be closed before it can be locked."
    if message_kind == "already_open":
        return f"{_sentence_case(container_label)} is already open."
    if message_kind == "already_closed":
        return f"{_sentence_case(container_label)} is already closed."
    if message_kind == "already_locked":
        return f"{_sentence_case(container_label)} is already locked."
    if message_kind == "already_unlocked":
        return f"{_sentence_case(container_label)} is already unlocked."
    return _sentence_case(container_label)


def _container_item_map(container: ContainerTarget) -> dict[str, ItemState]:
    return getattr(container, "container_items", {})


def _container_coin_amount(container: ContainerTarget) -> int:
    return max(0, int(getattr(container, "coins", 0) or 0))


def _set_container_coin_amount(container: ContainerTarget, amount: int) -> None:
    if hasattr(container, "coins"):
        setattr(container, "coins", max(0, int(amount)))


def _container_can_close(container: ContainerTarget) -> bool:
    if isinstance(container, ItemState):
        hydrate_misc_item_from_template(container)
    return bool(getattr(container, "can_close", False))


def _container_can_lock(container: ContainerTarget) -> bool:
    if isinstance(container, ItemState):
        hydrate_misc_item_from_template(container)
    return bool(getattr(container, "can_lock", bool(str(getattr(container, "lock_id", "")).strip())))


def _container_lock_id(container: ContainerTarget) -> str:
    if isinstance(container, ItemState):
        hydrate_misc_item_from_template(container)
    return str(getattr(container, "lock_id", "")).strip().lower()


def _container_is_closed(container: ContainerTarget) -> bool:
    if isinstance(container, ItemState):
        hydrate_misc_item_from_template(container)
    return bool(getattr(container, "is_closed", False))


def _container_is_locked(container: ContainerTarget) -> bool:
    if isinstance(container, ItemState):
        hydrate_misc_item_from_template(container)
    return bool(getattr(container, "is_locked", False))


def _container_contents_visible(container: ContainerTarget) -> bool:
    if _container_is_locked(container):
        return False
    if _container_can_close(container) and _container_is_closed(container):
        return False
    return True


def _container_access_message(container: ContainerTarget) -> str | None:
    if _container_is_locked(container):
        locked_message = str(getattr(container, "locked_message", "")).strip()
        return locked_message or _default_container_message(container, "locked")
    if _container_can_close(container) and _container_is_closed(container):
        closed_message = str(getattr(container, "closed_message", "")).strip()
        return closed_message or _default_container_message(container, "closed")
    return None


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

    if isinstance(container, ItemState):
        hydrate_misc_item_from_template(container)

    status_text = "Open"
    status_color = "containers.status.open"
    if _container_is_locked(container):
        status_text = "Locked"
        status_color = "containers.status.locked"
    elif _container_can_close(container) and _container_is_closed(container):
        status_text = "Closed"
        status_color = "containers.status.closed"
    rows.append(["Status", status_text])
    row_cell_colors.append(["containers.label_column", status_color])

    if _container_contents_visible(container):
        rows.append(["Coins", str(_container_coin_amount(container))])
        row_cell_colors.append(["containers.label_column", "containers.coins_value"])

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
                sample_item = next((item for item in container_items if item.name.strip().lower() == item_key), None)
                row_name = "Equipment" if sample_item is not None and bool(getattr(sample_item, "equippable", False)) else "Item"
                row_label_color = "containers.item.equipment_label" if row_name == "Equipment" else "containers.item.label"
                rows.append([row_name, item_label])
                row_cell_colors.append([row_label_color, item_colors[item_key]])
        else:
            rows.append(["Items", "None"])
            row_cell_colors.append(["containers.item.label", "containers.item.empty"])
    else:
        rows.append(["Contents", "Hidden while closed"])
        row_cell_colors.append(["containers.item.label", "containers.contents.hidden"])

    description = str(getattr(container, "description", "")).strip()
    if description:
        wrapped_description = wrap(description, width=_CONTAINER_DESCRIPTION_COLUMN_WIDTH) or [description]
        rows.append(["Description", wrapped_description[0]])
        row_cell_colors.append(["containers.description.heading", "containers.description.text"])
        for continuation_line in wrapped_description[1:]:
            rows.append(["", continuation_line])
            row_cell_colors.append(["containers.description.heading", "containers.description.text"])

    parts = build_menu_table_parts(
        title,
        ["Loot", "Contents"],
        rows,
        column_colors=["containers.label_column", "containers.location_value"],
        row_cell_colors=row_cell_colors,
        column_alignments=["left", "left"],
    )

    return display_command_result(session, parts)


def take_all_from_container(session: ClientSession, container: ContainerTarget):
    access_message = _container_access_message(container)
    if access_message is not None:
        return display_command_result(session, [
            build_part(access_message, "bright_white"),
        ])

    item_map = _container_item_map(container)
    taken_items = list(item_map.values())
    taken_items.sort(key=lambda item: item.name.lower())
    taken_coins = _container_coin_amount(container)

    if not taken_items and taken_coins <= 0:
        return display_error(f"{_sentence_case(_container_reference_text(container))} is empty.", session)

    if taken_coins > 0:
        _set_container_coin_amount(container, 0)
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
            newline_part(),
            build_part("Coins +", "bright_white"),
            build_part(str(taken_coins), "bright_cyan", True),
        ])
    for item in taken_items:
        parts.extend([
            newline_part(),
            build_part("You take ", "bright_white"),
            *_build_item_reference_parts(item),
            build_part(".", "bright_white"),
        ])

    return display_command_result(session, parts)


def take_item_from_container(session: ClientSession, container: ContainerTarget, item_selector: str):
    access_message = _container_access_message(container)
    if access_message is not None:
        return display_command_result(session, [
            build_part(access_message, "bright_white"),
        ])

    normalized = str(item_selector).strip().lower()
    if normalized == "all":
        return take_all_from_container(session, container)
    if normalized in {"coin", "coins"}:
        taken_coins = _container_coin_amount(container)
        if taken_coins <= 0:
            return display_error(f"{_container_label(container).title()} has no coins to take.", session)
        _set_container_coin_amount(container, 0)
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
    access_message = _container_access_message(container)
    if access_message is not None:
        return display_command_result(session, [
            build_part(access_message, "bright_white"),
        ])

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


def handle_container_command(
    session: ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> dict | None:
    normalized_verb = str(verb).strip().lower()
    if normalized_verb not in {"open", "ope", "op", "close", "clos", "clo", "cl", "lock", "unlock", "unl", "unlo", "unloc"}:
        return None

    if not args:
        return display_error(f"Usage: {normalized_verb} <container>", session)

    selector_text = " ".join(args).strip()
    key_selector: str | None = None
    if normalized_verb in {"lock", "unlock", "unl", "unlo", "unloc"}:
        selector_text, key_selector = _split_selector_and_key(selector_text)

    container, _, container_error = resolve_accessible_container(session, selector_text)
    if container is None:
        return display_error(container_error or f"No container matching '{selector_text}' is here.", session)

    container_label = _container_label(container)
    if isinstance(container, ItemState):
        hydrate_misc_item_from_template(container)
    can_close = _container_can_close(container)
    can_lock = _container_can_lock(container)
    lock_id = _container_lock_id(container)

    if normalized_verb in {"open", "ope", "op", "close", "clos", "clo", "cl"} and not can_close:
        return display_command_result(session, [
            build_part(f"The {container_label} cannot be opened or closed.", "bright_white"),
        ])

    if normalized_verb in {"open", "ope", "op"}:
        if _container_is_locked(container):
            locked_message = str(getattr(container, "locked_message", "")).strip()
            return display_command_result(session, [
                build_part(locked_message or _default_container_message(container, "locked"), "bright_white"),
            ])
        if not _container_is_closed(container):
            already_open_message = str(getattr(container, "already_open_message", "")).strip()
            return display_command_result(session, [
                build_part(already_open_message or _default_container_message(container, "already_open"), "bright_white"),
            ])

        container.is_closed = False
        open_message = str(getattr(container, "open_message", "")).strip()
        return display_command_result(session, [
            build_part(open_message or _default_container_message(container, "open"), "bright_white"),
        ])

    if normalized_verb in {"close", "clos", "clo", "cl"}:
        if _container_is_closed(container):
            already_closed_message = str(getattr(container, "already_closed_message", "")).strip()
            return display_command_result(session, [
                build_part(already_closed_message or _default_container_message(container, "already_closed"), "bright_white"),
            ])

        container.is_closed = True
        close_message = str(getattr(container, "close_message", "")).strip()
        return display_command_result(session, [
            build_part(close_message or _default_container_message(container, "close"), "bright_white"),
        ])

    if not can_lock or not lock_id:
        return display_command_result(session, [
            build_part(f"The {container_label} cannot be locked or unlocked.", "bright_white"),
        ])

    if normalized_verb in {"unlock", "unl", "unlo", "unloc"}:
        if not _container_is_locked(container):
            already_unlocked_message = str(getattr(container, "already_unlocked_message", "")).strip()
            return display_command_result(session, [
                build_part(already_unlocked_message or _default_container_message(container, "already_unlocked"), "bright_white"),
            ])

        key_item = _find_matching_key_item(session, lock_id, key_selector)
        if key_item is None:
            needs_key_message = str(getattr(container, "needs_key_message", "")).strip()
            return display_command_result(session, [
                build_part(needs_key_message or _default_container_message(container, "needs_key"), "bright_white"),
            ])

        container.is_locked = False
        unlock_message = str(getattr(container, "unlock_message", "")).strip()
        parts = [
            build_part(unlock_message or _default_container_message(container, "unlock"), "bright_white"),
        ]
        consume_message = consume_item_on_use(session, key_item)
        if consume_message:
            parts.extend([
                newline_part(),
                build_part(consume_message, "bright_white"),
            ])
        return display_command_result(session, parts)

    if _container_is_locked(container):
        already_locked_message = str(getattr(container, "already_locked_message", "")).strip()
        return display_command_result(session, [
            build_part(already_locked_message or _default_container_message(container, "already_locked"), "bright_white"),
        ])

    if not _container_is_closed(container):
        must_close_message = str(getattr(container, "must_close_to_lock_message", "")).strip()
        return display_command_result(session, [
            build_part(must_close_message or _default_container_message(container, "must_close_to_lock"), "bright_white"),
        ])

    key_item = _find_matching_key_item(session, lock_id, key_selector)
    if key_item is None:
        needs_key_message = str(getattr(container, "needs_key_message", "")).strip()
        return display_command_result(session, [
            build_part(needs_key_message or _default_container_message(container, "needs_key"), "bright_white"),
        ])

    container.is_locked = True
    lock_message = str(getattr(container, "lock_message", "")).strip()
    parts = [
        build_part(lock_message or _default_container_message(container, "lock"), "bright_white"),
    ]
    consume_message = consume_item_on_use(session, key_item)
    if consume_message:
        parts.extend([
            newline_part(),
            build_part(consume_message, "bright_white"),
        ])
    return display_command_result(session, parts)
