"""Inventory and room-item selector helpers."""

from inventory import get_item_keywords, is_item_equippable, parse_item_selector
from models import ClientSession, ItemState
from equipment_logic import list_worn_items


def _resolve_owned_item_selector(session: ClientSession, selector: str) -> tuple[ItemState | None, str | None, str | None]:
    requested_index, keywords, parse_error = parse_item_selector(selector)
    if parse_error is not None:
        return None, None, parse_error

    candidates: list[tuple[int, str, ItemState]] = []
    seen_item_ids: set[str] = set()

    for location_label, item in list_worn_items(session):
        if item.item_id in seen_item_ids:
            continue
        seen_item_ids.add(item.item_id)
        candidates.append((0, str(location_label).strip() or "equipped", item))

    for item in session.inventory_items.values():
        if item.item_id in seen_item_ids:
            continue
        seen_item_ids.add(item.item_id)
        candidates.append((1, "inventory", item))

    candidates.sort(key=lambda entry: (entry[0], entry[2].name.lower(), entry[2].item_id))

    matches: list[tuple[ItemState, str]] = []
    for _, location_label, item in candidates:
        item_keywords = get_item_keywords(item)
        if all(keyword in item_keywords for keyword in keywords):
            matches.append((item, location_label))

    if not matches:
        return None, None, f"You are not carrying or wearing anything matching '{selector}'."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, None, f"Only {len(matches)} match(es) found for '{selector}'."
        selected_item, location_label = matches[requested_index - 1]
        return selected_item, location_label, None

    selected_item, location_label = matches[0]
    return selected_item, location_label, None


def _resolve_inventory_selector(session: ClientSession, selector: str):
    requested_index, keywords, parse_error = parse_item_selector(selector)
    if parse_error is not None:
        return None, parse_error

    inventory_items = list(session.inventory_items.values())
    inventory_items.sort(key=lambda item: item.name.lower())

    matches = []
    for item in inventory_items:
        item_keywords = get_item_keywords(item)
        if all(keyword in item_keywords for keyword in keywords):
            matches.append(item)

    if not matches:
        return None, f"{selector} doesn't exist in inventory."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} match(es) found for '{selector}'."
        return matches[requested_index - 1], None

    return matches[0], None


def _resolve_misc_inventory_selector(session: ClientSession, selector: str):
    requested_index, keywords, parse_error = parse_item_selector(selector)
    if parse_error is not None:
        return None, parse_error

    misc_items = [item for item in session.inventory_items.values() if not is_item_equippable(item)]
    misc_items.sort(key=lambda item: item.name.lower())

    matches = []
    for item in misc_items:
        item_keywords = get_item_keywords(item)
        if all(keyword in item_keywords for keyword in keywords):
            matches.append(item)

    if not matches:
        return None, f"{selector} doesn't exist in inventory."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} match(es) found for '{selector}'."
        return matches[requested_index - 1], None

    return matches[0], None


def _resolve_wear_inventory_selector(session: ClientSession, selector: str) -> tuple[ItemState | None, str | None]:
    selected_item, resolve_error = _resolve_inventory_selector(session, selector)
    if selected_item is None:
        return None, resolve_error
    if not is_item_equippable(selected_item):
        return None, f"{selected_item.name} cannot be worn."
    return selected_item, None


def _list_room_ground_items(session: ClientSession, room_id: str):
    room_items = list(session.room_ground_items.get(room_id, {}).values())
    room_items.sort(key=lambda item: (item.name.lower(), item.item_id))
    return room_items


def _resolve_room_ground_matches(session: ClientSession, room_id: str, selector: str):
    requested_index, keywords, parse_error = parse_item_selector(selector)
    if parse_error is not None:
        return [], None, parse_error

    matches = []
    for item in _list_room_ground_items(session, room_id):
        item_keywords = get_item_keywords(item)
        if all(keyword in item_keywords for keyword in keywords):
            matches.append(item)

    if not matches:
        return [], requested_index, f"No room item matches '{selector}'."

    return matches, requested_index, None


def _resolve_room_ground_item_selector(session: ClientSession, room_id: str, selector: str) -> tuple[ItemState | None, str | None]:
    matches, requested_index, selector_error = _resolve_room_ground_matches(session, room_id, selector)
    if selector_error is not None:
        return None, selector_error

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} match(es) found for '{selector}'."
        return matches[requested_index - 1], None

    return matches[0], None


def _add_item_to_room_ground(session: ClientSession, room_id: str, item) -> None:
    room_items = session.room_ground_items.setdefault(room_id, {})
    room_items[item.item_id] = item


def _pickup_ground_item(session: ClientSession, room_id: str, item) -> None:
    session.room_ground_items.get(room_id, {}).pop(item.item_id, None)
    session.inventory_items[item.item_id] = item
