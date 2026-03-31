import re
from math import ceil

from assets import get_equipment_template_by_id, load_equipment_templates, load_hand_weight_config, load_wear_slot_config
from models import ClientSession, EquipmentItemState
from settings import BASE_PLAYER_ARMOR_CLASS


HAND_MAIN = "main_hand"
HAND_OFF = "off_hand"

_WEAR_SLOT_CONFIG = load_wear_slot_config()
_HAND_WEIGHT_CONFIG = load_hand_weight_config()
DEFAULT_WEAR_SLOTS = set(_WEAR_SLOT_CONFIG.get("wear_slots", []))
WEAR_SLOT_OPTIONS = dict(_WEAR_SLOT_CONFIG.get("slot_options", {}))
WEAR_LOCATION_ALIASES = dict(_WEAR_SLOT_CONFIG.get("location_aliases", {}))
_STRENGTH_ATTRIBUTE_ID = str(_HAND_WEIGHT_CONFIG.get("strength_attribute_id", "str"))
_HAND_REQUIREMENTS = dict(_HAND_WEIGHT_CONFIG.get("hand_requirements", {}))


def _get_supported_wear_slot_keys() -> set[str]:
    supported = set(DEFAULT_WEAR_SLOTS)
    for concrete_slots in WEAR_SLOT_OPTIONS.values():
        supported.update(concrete_slots)
    return supported


def resolve_wear_slot_alias(location: str) -> str | None:
    normalized = re.sub(r"[._]+", " ", location.strip().lower())
    normalized = re.sub(r"\s+", " ", normalized)
    if not normalized:
        return None

    alias_match = WEAR_LOCATION_ALIASES.get(normalized)
    if alias_match is not None:
        return alias_match

    candidate = normalized.replace(" ", "_")
    if candidate in _get_supported_wear_slot_keys():
        return candidate

    return None


def _get_wear_slot_keys(wear_slot: str) -> list[str]:
    return list(WEAR_SLOT_OPTIONS.get(wear_slot, [wear_slot]))


def _normalize_wear_slot_label(slot_key: str) -> str:
    return slot_key.replace("_", " ")


def _resolve_item_wear_slot_candidates(item: EquipmentItemState) -> tuple[list[str], str | None]:
    raw_candidates = [slot.strip().lower() for slot in item.wear_slots if slot.strip()]
    if not raw_candidates:
        wear_slot = item.wear_slot.strip().lower()
        if wear_slot:
            raw_candidates = [wear_slot]

    if not raw_candidates:
        return [], f"{item.name} has no wear slot configured."

    resolved_candidates: list[str] = []
    seen: set[str] = set()

    for slot in raw_candidates:
        if slot in DEFAULT_WEAR_SLOTS:
            for concrete_slot in _get_wear_slot_keys(slot):
                if concrete_slot in seen:
                    continue
                resolved_candidates.append(concrete_slot)
                seen.add(concrete_slot)
            continue

        if slot in seen:
            continue
        resolved_candidates.append(slot)
        seen.add(slot)

    return resolved_candidates, None


def _find_equipment_template_for_loot_name(loot_name: str) -> dict | None:
    normalized_loot_name = loot_name.strip().lower()
    if not normalized_loot_name:
        return None

    loot_tokens = {token for token in re.findall(r"[a-zA-Z0-9]+", normalized_loot_name) if token}
    for template in load_equipment_templates():
        template_name = str(template.get("name", "")).strip().lower()
        if template_name == normalized_loot_name:
            return template

        keywords = [str(keyword).strip().lower() for keyword in template.get("keywords", [])]
        if keywords and all(keyword in loot_tokens for keyword in keywords):
            return template

    return None


def get_equipment_template_for_item(item) -> dict | None:
    template_id = str(getattr(item, "template_id", "")).strip()
    if template_id:
        template = get_equipment_template_by_id(template_id)
        if template is not None:
            return template
    return _find_equipment_template_for_loot_name(str(getattr(item, "name", "")))


def is_item_equippable(item) -> bool:
    return isinstance(item, EquipmentItemState) or get_equipment_template_for_item(item) is not None


def list_equipment(session: ClientSession) -> list[EquipmentItemState]:
    equipment_items = [
        item
        for item in session.inventory_items.values()
        if isinstance(item, EquipmentItemState)
    ]
    equipment_items.sort(key=lambda item: (item.name.lower(), item.item_id))
    return equipment_items


def list_inventory_items(session: ClientSession) -> list[EquipmentItemState]:
    return list_equipment(session)


def get_equipped_main_hand(session: ClientSession) -> EquipmentItemState | None:
    item_id = session.equipment.equipped_main_hand_id
    if item_id is None:
        return None
    return session.equipment.equipped_items.get(item_id)


def get_equipped_off_hand(session: ClientSession) -> EquipmentItemState | None:
    item_id = session.equipment.equipped_off_hand_id
    if item_id is None:
        return None
    return session.equipment.equipped_items.get(item_id)


def get_held_weapon(session: ClientSession) -> EquipmentItemState | None:
    main_hand = get_equipped_main_hand(session)
    if main_hand is not None and main_hand.slot == "weapon":
        return main_hand

    off_hand = get_equipped_off_hand(session)
    if off_hand is not None and off_hand.slot == "weapon":
        return off_hand

    return None


def get_worn_item_for_slot(session: ClientSession, wear_slot: str) -> EquipmentItemState | None:
    normalized_slot = wear_slot.strip().lower()
    if not normalized_slot:
        return None

    slot_keys = [normalized_slot]
    if normalized_slot in DEFAULT_WEAR_SLOTS:
        slot_keys = _get_wear_slot_keys(normalized_slot)

    for slot_key in slot_keys:
        item_id = session.equipment.worn_item_ids.get(slot_key)
        if item_id is None:
            continue
        item = session.equipment.equipped_items.get(item_id)
        if item is not None:
            return item

    return None


def list_worn_items(session: ClientSession) -> list[tuple[str, EquipmentItemState]]:
    worn: list[tuple[str, EquipmentItemState]] = []

    main_hand = get_equipped_main_hand(session)
    if main_hand is not None:
        worn.append(("main hand", main_hand))

    off_hand = get_equipped_off_hand(session)
    if off_hand is not None:
        worn.append(("off hand", off_hand))

    for wear_slot in sorted(session.equipment.worn_item_ids.keys()):
        item_id = session.equipment.worn_item_ids[wear_slot]
        item = session.equipment.equipped_items.get(item_id)
        if item is None:
            continue
        worn.append((_normalize_wear_slot_label(wear_slot), item))

    return worn


def get_player_armor_class(session: ClientSession) -> int:
    armor_bonus = 0
    for wear_slot, item_id in session.equipment.worn_item_ids.items():
        if wear_slot and item_id:
            item = session.equipment.equipped_items.get(item_id)
            if item is None:
                continue
            armor_bonus += max(0, item.armor_class_bonus)
    return BASE_PLAYER_ARMOR_CLASS + armor_bonus


def _move_equipped_item_to_inventory(session: ClientSession, item_id: str) -> None:
    equipped_item = session.equipment.equipped_items.pop(item_id, None)
    if equipped_item is not None:
        session.inventory_items[item_id] = equipped_item


def _clear_item_slot_references(session: ClientSession, item_id: str) -> None:
    if session.equipment.equipped_main_hand_id == item_id:
        session.equipment.equipped_main_hand_id = None
    if session.equipment.equipped_off_hand_id == item_id:
        session.equipment.equipped_off_hand_id = None

    worn_slots_to_clear = [
        wear_slot
        for wear_slot, worn_item_id in session.equipment.worn_item_ids.items()
        if worn_item_id == item_id
    ]
    for wear_slot in worn_slots_to_clear:
        session.equipment.worn_item_ids.pop(wear_slot, None)


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


def resolve_equipped_selector(session: ClientSession, selector: str) -> tuple[EquipmentItemState | None, str | None]:
    requested_index, keywords, parse_error = _parse_selector(selector)
    if parse_error is not None:
        return None, parse_error

    equipped_items: list[EquipmentItemState] = []
    seen_ids: set[str] = set()
    for _, item in list_worn_items(session):
        if item.item_id in seen_ids:
            continue
        equipped_items.append(item)
        seen_ids.add(item.item_id)

    matches: list[EquipmentItemState] = []
    for item in equipped_items:
        item_keywords = get_item_keywords(item)
        if all(keyword in item_keywords for keyword in keywords):
            matches.append(item)

    if not matches:
        return None, f"No equipped item matches '{selector}'."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} match(es) found for '{selector}'."
        return matches[requested_index - 1], None

    return matches[0], None


def _required_strength_for_hand(weight: int, hand: str) -> int:
    hand_config = _HAND_REQUIREMENTS.get(hand, {})
    multiplier = float(hand_config.get("weight_multiplier", 1.0))
    return max(0, int(ceil(max(0, weight) * multiplier)))


def can_player_equip_hand(session: ClientSession, item: EquipmentItemState, hand: str) -> tuple[bool, str]:
    """Check whether a weapon can be equipped in the requested hand."""
    article = "An" if item.name[0].lower() in "aeiou" else "A"
    if hand == HAND_OFF and not item.can_hold:
        return False, f"{article} {item.name} cannot be held in your off hand."

    weight = max(0, item.weight)
    player_strength = int(session.player.attributes.get(_STRENGTH_ATTRIBUTE_ID, 0))
    required_strength = _required_strength_for_hand(weight, hand)
    if player_strength >= required_strength:
        return True, ""

    action = "hold" if hand == HAND_OFF else "wield"
    return False, f"{article} {item.name} is too heavy to {action}."


def equip_item(session: ClientSession, item: EquipmentItemState, hand: str | None = None) -> tuple[bool, str]:
    if item.slot != "weapon":
        return False, f"{item.name} cannot be equipped as a weapon."

    target_hand = (hand or HAND_MAIN).strip().lower()
    if target_hand not in {HAND_MAIN, HAND_OFF}:
        return False, "Hand must be main or off."

    can_equip, equip_error = can_player_equip_hand(session, item, target_hand)
    if not can_equip:
        return False, equip_error

    if item.item_id not in session.inventory_items:
        return False, f"{item.name} is not in your inventory."

    previous_main_id = session.equipment.equipped_main_hand_id
    previous_off_id = session.equipment.equipped_off_hand_id

    _clear_item_slot_references(session, item.item_id)

    if target_hand == HAND_MAIN:
        session.equipment.equipped_main_hand_id = item.item_id
        if session.equipment.equipped_off_hand_id == item.item_id:
            session.equipment.equipped_off_hand_id = None
        if previous_main_id is not None and previous_main_id != item.item_id:
            _clear_item_slot_references(session, previous_main_id)
            _move_equipped_item_to_inventory(session, previous_main_id)
    else:
        session.equipment.equipped_off_hand_id = item.item_id
        if session.equipment.equipped_main_hand_id == item.item_id:
            session.equipment.equipped_main_hand_id = None
        if previous_off_id is not None and previous_off_id != item.item_id:
            _clear_item_slot_references(session, previous_off_id)
            _move_equipped_item_to_inventory(session, previous_off_id)

    session.equipment.equipped_items[item.item_id] = item
    session.inventory_items.pop(item.item_id, None)

    return True, target_hand


def wear_item(session: ClientSession, item: EquipmentItemState, target_wear_slot: str | None = None) -> tuple[bool, str]:
    if item.slot != "armor":
        return False, f"{item.name} cannot be worn."

    wear_slot_candidates, slot_error = _resolve_item_wear_slot_candidates(item)
    if slot_error is not None:
        return False, slot_error

    if target_wear_slot is not None:
        normalized_target_slot = target_wear_slot.strip().lower()
        if normalized_target_slot not in wear_slot_candidates:
            allowed = ", ".join(_normalize_wear_slot_label(slot) for slot in wear_slot_candidates)
            return False, f"{item.name} cannot be worn on your {_normalize_wear_slot_label(normalized_target_slot)}. Available slots: {allowed}."
        wear_slot_candidates = [normalized_target_slot]

    if item.item_id not in session.inventory_items:
        return False, f"{item.name} is not in your inventory."

    target_slot_key: str | None = None
    for slot_key in wear_slot_candidates:
        current_item_id = session.equipment.worn_item_ids.get(slot_key)
        if current_item_id is None or current_item_id == item.item_id:
            target_slot_key = slot_key
            break

    if target_slot_key is None:
        slot_labels = [_normalize_wear_slot_label(slot_key) for slot_key in wear_slot_candidates]
        if len(slot_labels) == 1:
            return False, f"You are already wearing something on your {slot_labels[0]}."
        return False, f"No available wear slot for {item.name}. Tried: {', '.join(slot_labels)}."

    _clear_item_slot_references(session, item.item_id)
    session.equipment.worn_item_ids[target_slot_key] = item.item_id
    session.equipment.equipped_items[item.item_id] = item
    session.inventory_items.pop(item.item_id, None)
    return True, _normalize_wear_slot_label(target_slot_key)


def unequip_item(session: ClientSession, item: EquipmentItemState) -> bool:
    item_id = item.item_id
    if item_id not in session.equipment.equipped_items:
        return False

    _clear_item_slot_references(session, item_id)
    _move_equipped_item_to_inventory(session, item_id)
    return True


def remove_item(session: ClientSession, item: EquipmentItemState) -> None:
    item_id = item.item_id
    _clear_item_slot_references(session, item_id)
    session.equipment.equipped_items.pop(item_id, None)
    session.inventory_items.pop(item_id, None)