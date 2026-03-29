import re

from models import ClientSession, EquipmentItemState


HAND_MAIN = "main_hand"
HAND_OFF = "off_hand"


def list_equipment(session: ClientSession) -> list[EquipmentItemState]:
    equipment_items = list(session.equipment.items.values())
    equipment_items.sort(key=lambda item: (item.name.lower(), item.item_id))
    return equipment_items


def get_equipped_main_hand(session: ClientSession) -> EquipmentItemState | None:
    item_id = session.equipment.equipped_main_hand_id
    if item_id is None:
        return None
    return session.equipment.items.get(item_id)


def get_equipped_off_hand(session: ClientSession) -> EquipmentItemState | None:
    item_id = session.equipment.equipped_off_hand_id
    if item_id is None:
        return None
    return session.equipment.items.get(item_id)


def get_held_weapon(session: ClientSession) -> EquipmentItemState | None:
    main_hand = get_equipped_main_hand(session)
    if main_hand is not None and main_hand.slot == "weapon":
        return main_hand

    off_hand = get_equipped_off_hand(session)
    if off_hand is not None and off_hand.slot == "weapon":
        return off_hand

    return None


def _name_keywords(name: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[a-zA-Z0-9]+", name)}


def get_item_keywords(item: EquipmentItemState) -> set[str]:
    keywords = _name_keywords(item.name)
    keywords.update(_name_keywords(item.template_id))
    keywords.update(keyword.strip().lower() for keyword in item.keywords if keyword.strip())
    return keywords


def _parse_selector(selector: str) -> tuple[int | None, list[str], str | None]:
    normalized = selector.strip().lower()
    if not normalized:
        return None, [], "Provide equipment keywords, e.g. training.sword"

    parts = [part for part in normalized.split(".") if part]
    if not parts:
        return None, [], "Provide equipment keywords, e.g. training.sword"

    match_index: int | None = None
    if parts[0].isdigit():
        match_index = int(parts[0])
        parts = parts[1:]
        if match_index <= 0:
            return None, [], "Selector index must be 1 or greater."

    if not parts:
        return None, [], "Provide at least one equipment keyword after the index."

    return match_index, parts, None


def _find_selector_matches(session: ClientSession, selector: str) -> tuple[list[EquipmentItemState], int | None, str | None]:
    requested_index, keywords, parse_error = _parse_selector(selector)
    if parse_error is not None:
        return [], None, parse_error

    matches: list[EquipmentItemState] = []
    for item in list_equipment(session):
        item_keywords = get_item_keywords(item)
        if all(keyword in item_keywords for keyword in keywords):
            matches.append(item)

    return matches, requested_index, None


def resolve_equipment_selector(session: ClientSession, selector: str) -> tuple[EquipmentItemState | None, str | None]:
    matches, requested_index, error = _find_selector_matches(session, selector)
    if error is not None:
        return None, error

    if not matches:
        return None, f"No equipment matches '{selector}'."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} match(es) found for '{selector}'."
        return matches[requested_index - 1], None

    return matches[0], None


def equip_item(session: ClientSession, item: EquipmentItemState, hand: str | None = None) -> tuple[bool, str]:
    if item.slot != "weapon":
        return False, f"{item.name} cannot be equipped as a weapon."

    target_hand = (hand or item.preferred_hand or HAND_MAIN).strip().lower()
    if target_hand not in {HAND_MAIN, HAND_OFF}:
        return False, "Hand must be main or off."

    if target_hand == HAND_MAIN:
        session.equipment.equipped_main_hand_id = item.item_id
        if session.equipment.equipped_off_hand_id == item.item_id:
            session.equipment.equipped_off_hand_id = None
    else:
        session.equipment.equipped_off_hand_id = item.item_id
        if session.equipment.equipped_main_hand_id == item.item_id:
            session.equipment.equipped_main_hand_id = None

    return True, target_hand


def remove_item(session: ClientSession, item: EquipmentItemState) -> None:
    session.equipment.items.pop(item.item_id, None)
    if session.equipment.equipped_main_hand_id == item.item_id:
        session.equipment.equipped_main_hand_id = None
    if session.equipment.equipped_off_hand_id == item.item_id:
        session.equipment.equipped_off_hand_id = None