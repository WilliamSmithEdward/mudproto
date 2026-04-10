import re
import uuid

from assets import get_gear_template_by_id, get_item_template_by_id, load_gear_templates, load_item_templates
from models import ClientSession, ItemState


def build_equippable_item_from_template(template: dict, *, item_id: str | None = None) -> ItemState:
    resolved_item_id = (item_id or f"item-{uuid.uuid4().hex[:8]}").strip()
    wear_slots = [str(slot).strip().lower() for slot in template.get("wear_slots", []) if str(slot).strip()]
    wear_slot = wear_slots[0] if wear_slots else ""
    return ItemState(
        item_id=resolved_item_id,
        template_id=str(template.get("template_id", "")).strip(),
        name=str(template.get("name", "Item")).strip() or "Item",
        description=str(template.get("description", "")),
        keywords=[str(keyword).strip().lower() for keyword in template.get("keywords", []) if str(keyword).strip()],
        equippable=True,
        slot=str(template.get("slot", "")).strip().lower(),
        weapon_type=str(template.get("weapon_type", "unarmed")).strip().lower() or "unarmed",
        can_hold=bool(template.get("can_hold", False)),
        can_two_hand=bool(template.get("can_two_hand", False)),
        requires_two_hands=bool(template.get("requires_two_hands", False)),
        weight=max(0, int(template.get("weight", 0))),
        damage_dice_count=int(template.get("damage_dice_count", 0)),
        damage_dice_sides=int(template.get("damage_dice_sides", 0)),
        damage_roll_modifier=int(template.get("damage_roll_modifier", 0)),
        hit_roll_modifier=int(template.get("hit_roll_modifier", 0)),
        attack_damage_bonus=int(template.get("attack_damage_bonus", 0)),
        attacks_per_round_bonus=int(template.get("attacks_per_round_bonus", 0)),
        armor_class_bonus=int(template.get("armor_class_bonus", 0)),
        wear_slot=wear_slot,
        wear_slots=wear_slots,
        item_type="equipment",
        persistent=bool(template.get("persistent", True)),
    )


def build_misc_item_from_template(template: dict, *, item_id: str | None = None) -> ItemState:
    resolved_item_id = (item_id or f"item-{uuid.uuid4().hex[:8]}").strip()
    raw_item_type = str(template.get("item_type", "")).strip().lower()
    if not raw_item_type:
        raw_item_type = "consumable" if str(template.get("effect_type", "")).strip() else "misc"

    return ItemState(
        item_id=resolved_item_id,
        template_id=str(template.get("template_id", "")).strip(),
        name=str(template.get("name", "Item")).strip() or "Item",
        description=str(template.get("description", "")),
        keywords=[str(keyword).strip().lower() for keyword in template.get("keywords", []) if str(keyword).strip()],
        item_type=raw_item_type,
        persistent=bool(template.get("persistent", True)),
        lock_ids=[str(lock_id).strip().lower() for lock_id in template.get("lock_ids", []) if str(lock_id).strip()],
        portable=bool(template.get("portable", template.get("carryable", True))),
        consume_on_use=bool(template.get("consume_on_use", False)),
        consume_message=str(template.get("consume_message", "")).strip(),
        decay_game_hours=max(0, int(template.get("decay_game_hours", 0))),
        remaining_game_hours=max(0, int(template.get("decay_game_hours", 0))),
        decay_message=str(template.get("decay_message", "")).strip(),
        can_close=bool(template.get("can_close", raw_item_type == "container")),
        can_lock=bool(template.get("can_lock", bool(str(template.get("lock_id", "")).strip()))),
        lock_id=str(template.get("lock_id", "")).strip().lower(),
        is_closed=bool(template.get("is_closed", False)),
        is_locked=bool(template.get("is_locked", False)),
        open_message=str(template.get("open_message", "")).strip(),
        close_message=str(template.get("close_message", "")).strip(),
        lock_message=str(template.get("lock_message", "")).strip(),
        unlock_message=str(template.get("unlock_message", "")).strip(),
        closed_message=str(template.get("closed_message", "")).strip(),
        locked_message=str(template.get("locked_message", "")).strip(),
        needs_key_message=str(template.get("needs_key_message", "")).strip(),
        must_close_to_lock_message=str(template.get("must_close_to_lock_message", "")).strip(),
        already_open_message=str(template.get("already_open_message", "")).strip(),
        already_closed_message=str(template.get("already_closed_message", "")).strip(),
        already_locked_message=str(template.get("already_locked_message", "")).strip(),
        already_unlocked_message=str(template.get("already_unlocked_message", "")).strip(),
        container_items={},
    )


def _find_gear_template_for_item_name(item_name: str) -> dict | None:
    normalized_item_name = item_name.strip().lower()
    if not normalized_item_name:
        return None

    item_tokens = {token for token in re.findall(r"[a-zA-Z0-9]+", normalized_item_name) if token}
    for template in load_gear_templates():
        template_name = str(template.get("name", "")).strip().lower()
        if template_name == normalized_item_name:
            return template

        keywords = [str(keyword).strip().lower() for keyword in template.get("keywords", [])]
        if keywords and all(keyword in item_tokens for keyword in keywords):
            return template

    return None


def get_gear_template_for_item(item: ItemState) -> dict | None:
    template_id = str(getattr(item, "template_id", "")).strip()
    if template_id:
        template = get_gear_template_by_id(template_id)
        if template is not None:
            return template
    return _find_gear_template_for_item_name(str(getattr(item, "name", "")))


def _find_item_template_for_item_name(item_name: str) -> dict | None:
    normalized_item_name = item_name.strip().lower()
    if not normalized_item_name:
        return None

    item_tokens = {token for token in re.findall(r"[a-zA-Z0-9]+", normalized_item_name) if token}
    for template in load_item_templates():
        template_name = str(template.get("name", "")).strip().lower()
        if template_name == normalized_item_name:
            return template

        keywords = [str(keyword).strip().lower() for keyword in template.get("keywords", [])]
        if keywords and all(keyword in item_tokens for keyword in keywords):
            return template

    return None


def get_item_template_for_item(item: ItemState) -> dict | None:
    template_id = str(getattr(item, "template_id", "")).strip()
    if template_id:
        template = get_item_template_by_id(template_id)
        if template is not None:
            return template
    return _find_item_template_for_item_name(str(getattr(item, "name", "")))


def hydrate_misc_item_from_template(item: ItemState, template: dict | None = None) -> ItemState:
    resolved_template = template or get_item_template_for_item(item)
    if resolved_template is None:
        return item

    item.item_type = str(resolved_template.get("item_type", getattr(item, "item_type", "misc"))).strip().lower() or "misc"
    item.persistent = bool(resolved_template.get("persistent", getattr(item, "persistent", True)))
    item.portable = bool(resolved_template.get("portable", resolved_template.get("carryable", getattr(item, "portable", True))))
    item.consume_on_use = bool(resolved_template.get("consume_on_use", getattr(item, "consume_on_use", False)))
    item.consume_message = str(getattr(item, "consume_message", "") or resolved_template.get("consume_message", "")).strip()
    decay_game_hours = max(0, int(resolved_template.get("decay_game_hours", getattr(item, "decay_game_hours", 0))))
    item.decay_game_hours = decay_game_hours
    existing_remaining_hours = int(getattr(item, "remaining_game_hours", 0))
    if decay_game_hours <= 0:
        item.remaining_game_hours = 0
    elif existing_remaining_hours <= 0 or existing_remaining_hours > decay_game_hours:
        item.remaining_game_hours = decay_game_hours
    else:
        item.remaining_game_hours = existing_remaining_hours
    item.decay_message = str(getattr(item, "decay_message", "") or resolved_template.get("decay_message", "")).strip()
    item.can_close = bool(resolved_template.get("can_close", getattr(item, "can_close", item.item_type == "container")))
    item.can_lock = bool(resolved_template.get("can_lock", getattr(item, "can_lock", bool(str(resolved_template.get("lock_id", getattr(item, "lock_id", ""))).strip()))))
    item.lock_id = str(resolved_template.get("lock_id", getattr(item, "lock_id", ""))).strip().lower()
    item.is_closed = bool(getattr(item, "is_closed", bool(resolved_template.get("is_closed", False))))
    item.is_locked = bool(getattr(item, "is_locked", bool(resolved_template.get("is_locked", False))))
    item.open_message = str(getattr(item, "open_message", "") or resolved_template.get("open_message", "")).strip()
    item.close_message = str(getattr(item, "close_message", "") or resolved_template.get("close_message", "")).strip()
    item.lock_message = str(getattr(item, "lock_message", "") or resolved_template.get("lock_message", "")).strip()
    item.unlock_message = str(getattr(item, "unlock_message", "") or resolved_template.get("unlock_message", "")).strip()
    item.closed_message = str(getattr(item, "closed_message", "") or resolved_template.get("closed_message", "")).strip()
    item.locked_message = str(getattr(item, "locked_message", "") or resolved_template.get("locked_message", "")).strip()
    item.needs_key_message = str(getattr(item, "needs_key_message", "") or resolved_template.get("needs_key_message", "")).strip()
    item.must_close_to_lock_message = str(getattr(item, "must_close_to_lock_message", "") or resolved_template.get("must_close_to_lock_message", "")).strip()
    item.already_open_message = str(getattr(item, "already_open_message", "") or resolved_template.get("already_open_message", "")).strip()
    item.already_closed_message = str(getattr(item, "already_closed_message", "") or resolved_template.get("already_closed_message", "")).strip()
    item.already_locked_message = str(getattr(item, "already_locked_message", "") or resolved_template.get("already_locked_message", "")).strip()
    item.already_unlocked_message = str(getattr(item, "already_unlocked_message", "") or resolved_template.get("already_unlocked_message", "")).strip()
    if not getattr(item, "lock_ids", None):
        item.lock_ids = [
            str(lock_id).strip().lower()
            for lock_id in resolved_template.get("lock_ids", [])
            if str(lock_id).strip()
        ]
    if not item.description:
        item.description = str(resolved_template.get("description", ""))
    if not item.keywords:
        item.keywords = [str(keyword).strip().lower() for keyword in resolved_template.get("keywords", []) if str(keyword).strip()]
    return item


def item_unlocks_lock(item: ItemState, lock_id: str) -> bool:
    normalized_lock_id = str(lock_id).strip().lower()
    if not normalized_lock_id:
        return False
    hydrate_misc_item_from_template(item)
    return normalized_lock_id in {
        str(candidate).strip().lower()
        for candidate in getattr(item, "lock_ids", [])
        if str(candidate).strip()
    }


def consume_item_on_use(session: ClientSession, item: ItemState) -> str | None:
    hydrate_misc_item_from_template(item)
    if not bool(getattr(item, "consume_on_use", False)):
        return None

    session.inventory_items.pop(item.item_id, None)
    consume_message = str(getattr(item, "consume_message", "")).strip()
    if consume_message:
        return consume_message
    return f"{item.name.strip() or 'The key'} crumbles to dust after its magic is spent."


def _item_decay_expires(item: ItemState) -> bool:
    hydrate_misc_item_from_template(item)
    decay_game_hours = max(0, int(getattr(item, "decay_game_hours", 0)))
    if decay_game_hours <= 0:
        return False

    remaining_game_hours = int(getattr(item, "remaining_game_hours", 0))
    if remaining_game_hours <= 0 or remaining_game_hours > decay_game_hours:
        remaining_game_hours = decay_game_hours

    remaining_game_hours -= 1
    item.remaining_game_hours = max(0, remaining_game_hours)
    return item.remaining_game_hours <= 0


def tick_item_decay_map(item_map: dict[str, ItemState]) -> list[ItemState]:
    expired_items: list[ItemState] = []
    for item_id, item in list(item_map.items()):
        nested_items = getattr(item, "container_items", {})
        if isinstance(nested_items, dict) and nested_items:
            expired_items.extend(tick_item_decay_map(nested_items))
        if _item_decay_expires(item):
            item_map.pop(item_id, None)
            expired_items.append(item)
    return expired_items


def tick_item_decay_list(items: list[ItemState]) -> list[ItemState]:
    expired_items: list[ItemState] = []
    retained_items: list[ItemState] = []
    for item in list(items):
        nested_items = getattr(item, "container_items", {})
        if isinstance(nested_items, dict) and nested_items:
            expired_items.extend(tick_item_decay_map(nested_items))
        if _item_decay_expires(item):
            expired_items.append(item)
            continue
        retained_items.append(item)

    if len(retained_items) != len(items):
        items[:] = retained_items
    return expired_items


def is_item_equippable(item: ItemState) -> bool:
    if bool(getattr(item, "equippable", False)):
        return True

    template = get_gear_template_for_item(item)
    if template is None:
        return False

    item.equippable = True
    item.slot = str(template.get("slot", item.slot)).strip().lower()
    item.weapon_type = str(template.get("weapon_type", item.weapon_type)).strip().lower() or "unarmed"
    item.can_hold = bool(template.get("can_hold", item.can_hold))
    item.can_two_hand = bool(template.get("can_two_hand", item.can_two_hand))
    item.requires_two_hands = bool(template.get("requires_two_hands", item.requires_two_hands))
    item.weight = max(0, int(template.get("weight", item.weight)))
    item.damage_dice_count = int(template.get("damage_dice_count", item.damage_dice_count))
    item.damage_dice_sides = int(template.get("damage_dice_sides", item.damage_dice_sides))
    item.damage_roll_modifier = int(template.get("damage_roll_modifier", item.damage_roll_modifier))
    item.hit_roll_modifier = int(template.get("hit_roll_modifier", item.hit_roll_modifier))
    item.attack_damage_bonus = int(template.get("attack_damage_bonus", item.attack_damage_bonus))
    item.attacks_per_round_bonus = int(template.get("attacks_per_round_bonus", item.attacks_per_round_bonus))
    item.armor_class_bonus = int(template.get("armor_class_bonus", item.armor_class_bonus))
    item.wear_slots = [str(slot).strip().lower() for slot in template.get("wear_slots", []) if str(slot).strip()]
    item.wear_slot = item.wear_slots[0] if item.wear_slots else ""
    if not item.description:
        item.description = str(template.get("description", ""))
    if not item.keywords:
        item.keywords = [str(keyword).strip().lower() for keyword in template.get("keywords", []) if str(keyword).strip()]
    return True


def list_equippable_inventory_items(session: ClientSession) -> list[ItemState]:
    equippable_items = [
        item
        for item in session.inventory_items.values()
        if is_item_equippable(item)
    ]
    equippable_items.sort(key=lambda item: (item.name.lower(), item.item_id))
    return equippable_items


def _name_keywords(name: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[a-zA-Z0-9]+", name)}


def get_item_keywords(item: ItemState) -> set[str]:
    keywords = _name_keywords(item.name)
    keywords.update(_name_keywords(item.template_id))
    keywords.update(keyword.strip().lower() for keyword in item.keywords if keyword.strip())
    return keywords


def parse_item_selector(selector: str) -> tuple[int | None, list[str], str | None]:
    normalized = selector.strip().lower()
    if not normalized:
        return None, [], "Provide equipment keywords, e.g. training sword"

    parts = [part for part in re.split(r"[.\s]+", normalized) if part]
    if not parts:
        return None, [], "Provide equipment keywords, e.g. training sword"

    match_index: int | None = None
    if parts[0].isdigit():
        match_index = int(parts[0])
        parts = parts[1:]
        if match_index <= 0:
            return None, [], "Selector index must be 1 or greater."

    if not parts:
        return None, [], "Provide at least one equipment keyword after the index."

    return match_index, parts, None


def _find_selector_matches(session: ClientSession, selector: str) -> tuple[list[ItemState], int | None, str | None]:
    requested_index, keywords, parse_error = parse_item_selector(selector)
    if parse_error is not None:
        return [], None, parse_error

    matches: list[ItemState] = []
    for item in list_equippable_inventory_items(session):
        item_keywords = get_item_keywords(item)
        if all(keyword in item_keywords for keyword in keywords):
            matches.append(item)

    return matches, requested_index, None


def resolve_equipment_selector(session: ClientSession, selector: str) -> tuple[ItemState | None, str | None]:
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