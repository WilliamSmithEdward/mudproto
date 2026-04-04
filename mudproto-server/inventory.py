import re
import uuid

from assets import get_gear_template_by_id, load_gear_templates
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