"""Shared commerce helpers for merchant inventory, pricing, and trade resolution."""

import math
import re
import uuid

from assets import get_gear_template_by_id, get_item_template_by_id
from display_core import build_menu_table_parts, build_part, newline_part
from display_feedback import display_command_result
from equipment_logic import unequip_item
from inventory import build_equippable_item_from_template, is_item_equippable
from models import ClientSession, ItemState

OutboundMessage = dict[str, object]


def _tokenize_selector_value(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-zA-Z0-9]+", value.strip().lower()) if token}


def _parse_trade_selector(selector: str) -> tuple[int | None, list[str], str | None]:
    normalized = selector.strip().lower()
    if not normalized:
        return None, [], "Provide an item selector."

    parts = [part for part in normalized.split(".") if part]
    if not parts:
        return None, [], "Provide an item selector."

    requested_index: int | None = None
    if parts[0].isdigit():
        requested_index = int(parts[0])
        parts = parts[1:]
        if requested_index <= 0:
            return None, [], "Selector index must be 1 or greater."

    if not parts:
        return None, [], "Provide at least one selector keyword after the index."

    return requested_index, parts, None


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _get_trade_template_by_id(template_id: str) -> tuple[dict | None, str | None]:
    gear_template = get_gear_template_by_id(template_id)
    if gear_template is not None:
        return gear_template, "Gear"

    item_template = get_item_template_by_id(template_id)
    if item_template is not None:
        return item_template, "Item"

    return None, None


def _resolve_template_coin_value(template: dict, *, template_kind: str) -> int:
    explicit_value = max(0, _as_int(template.get("coin_value", 0)))
    if explicit_value > 0:
        return explicit_value

    if template_kind == "Gear":
        slot = str(template.get("slot", "")).strip().lower()
        if slot == "weapon":
            return max(
                5,
                12
                + max(0, _as_int(template.get("damage_dice_count", 0))) * max(0, _as_int(template.get("damage_dice_sides", 0)))
                + max(0, _as_int(template.get("damage_roll_modifier", 0))) * 3
                + max(0, _as_int(template.get("hit_roll_modifier", 0))) * 3
                + max(0, _as_int(template.get("attack_damage_bonus", 0))) * 5
                + max(0, _as_int(template.get("attacks_per_round_bonus", 0))) * 8
                + max(0, _as_int(template.get("weight", 0))),
            )

        wear_slots = template.get("wear_slots", [])
        if not isinstance(wear_slots, list):
            wear_slots = []

        return max(
            4,
            10
            + max(0, _as_int(template.get("armor_class_bonus", 0))) * 12
            + len(wear_slots) * 2
            + max(0, _as_int(template.get("weight", 0))),
        )

    return max(
        3,
        8
        + max(0, _as_int(template.get("effect_amount", 0))) // 2
        + int(max(0.0, float(template.get("use_lag_seconds", 0.0))) * 5),
    )


def _resolve_item_coin_value(item: ItemState) -> int:
    template_id = str(getattr(item, "template_id", "")).strip()
    if template_id:
        template, template_kind = _get_trade_template_by_id(template_id)
        if template is not None and template_kind is not None:
            return _resolve_template_coin_value(template, template_kind=template_kind)

    if is_item_equippable(item):
        return _resolve_template_coin_value({
            "slot": item.slot,
            "damage_dice_count": item.damage_dice_count,
            "damage_dice_sides": item.damage_dice_sides,
            "damage_roll_modifier": item.damage_roll_modifier,
            "hit_roll_modifier": item.hit_roll_modifier,
            "attack_damage_bonus": item.attack_damage_bonus,
            "attacks_per_round_bonus": item.attacks_per_round_bonus,
            "armor_class_bonus": item.armor_class_bonus,
            "wear_slots": list(item.wear_slots),
            "weight": item.weight,
        }, template_kind="Gear")

    return max(1, 2 + len(_tokenize_selector_value(item.name)) + max(0, _as_int(getattr(item, "weight", 0))))


def _list_room_merchants(session: ClientSession):
    merchants = [
        entity
        for entity in session.entities.values()
        if entity.room_id == session.player.current_room_id
        and entity.is_alive
        and bool(getattr(entity, "is_merchant", False))
    ]
    merchants.sort(key=lambda entity: (entity.name.lower(), entity.spawn_sequence, entity.entity_id))
    return merchants


def _resolve_room_merchant(session: ClientSession):
    merchants = _list_room_merchants(session)
    if not merchants:
        return None, "There is no merchant here."
    return merchants[0], None


def _get_merchant_buy_price(merchant, template: dict, *, template_kind: str) -> int:
    base_value = _resolve_template_coin_value(template, template_kind=template_kind)
    markup = max(0.1, float(getattr(merchant, "merchant_buy_markup", 1.0)))
    return max(1, int(math.ceil(base_value * markup)))


def _get_merchant_sale_offer(merchant, item: ItemState) -> int:
    base_value = _resolve_item_coin_value(item)
    sell_ratio = max(0.0, min(1.0, float(getattr(merchant, "merchant_sell_ratio", 0.5))))
    return max(1, int(math.floor(base_value * sell_ratio)))


def _get_merchant_resale_price(merchant, item: ItemState) -> int:
    base_value = _resolve_item_coin_value(item)
    markup = max(0.1, float(getattr(merchant, "merchant_buy_markup", 1.0)))
    return max(1, int(math.ceil(base_value * markup)))


def _build_resale_stack_key(item: ItemState) -> str:
    template_id = str(getattr(item, "template_id", "")).strip().lower()
    if template_id:
        return f"template:{template_id}"

    normalized_name = str(getattr(item, "name", "")).strip().lower()
    if normalized_name:
        return f"name:{normalized_name}"

    return f"item:{item.item_id}"


def _get_merchant_base_stock_entries(merchant) -> list[dict[str, object]]:
    stock_entries = getattr(merchant, "merchant_inventory", None)
    if isinstance(stock_entries, list):
        return stock_entries

    normalized_entries = [
        {
            "template_id": str(template_id).strip(),
            "infinite": True,
            "quantity": 1,
        }
        for template_id in getattr(merchant, "merchant_inventory_template_ids", [])
        if str(template_id).strip()
    ]
    merchant.merchant_inventory = normalized_entries
    return normalized_entries


def _find_merchant_base_stock_entry(merchant, template_id: str) -> dict[str, object] | None:
    normalized_template_id = template_id.strip().lower()
    if not normalized_template_id:
        return None

    for stock_entry in _get_merchant_base_stock_entries(merchant):
        candidate_template_id = str(stock_entry.get("template_id", "")).strip().lower()
        if candidate_template_id == normalized_template_id:
            return stock_entry

    return None


def _append_item_to_merchant_stock(merchant, item: ItemState) -> None:
    template_id = str(getattr(item, "template_id", "")).strip()
    if template_id:
        stock_entry = _find_merchant_base_stock_entry(merchant, template_id)
        if stock_entry is not None:
            if bool(stock_entry.get("infinite", False)):
                return
            stock_entry["quantity"] = max(0, _as_int(stock_entry.get("quantity", 0))) + 1
            return

    merchant_resale_items = getattr(merchant, "merchant_resale_items", None)
    if not isinstance(merchant_resale_items, dict):
        merchant_resale_items = {}
        merchant.merchant_resale_items = merchant_resale_items

    stack_key = _build_resale_stack_key(item)
    resale_stack = merchant_resale_items.get(stack_key)
    if not isinstance(resale_stack, dict):
        resale_stack = {
            "template_id": template_id,
            "name": str(item.name).strip() or "Item",
            "keywords": [str(keyword).strip().lower() for keyword in item.keywords if str(keyword).strip()],
            "items": [],
        }
        merchant_resale_items[stack_key] = resale_stack

    stack_items = resale_stack.get("items")
    if not isinstance(stack_items, list):
        stack_items = []
        resale_stack["items"] = stack_items
    stack_items.append(item)


def _build_merchant_stock_entries(merchant) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for stock_entry in _get_merchant_base_stock_entries(merchant):
        template_id = str(stock_entry.get("template_id", "")).strip()
        if not template_id:
            continue

        template, template_kind = _get_trade_template_by_id(template_id)
        if template is None or template_kind is None:
            continue

        infinite = bool(stock_entry.get("infinite", False))
        quantity = max(0, _as_int(stock_entry.get("quantity", 1), 1))
        if not infinite and quantity <= 0:
            continue

        base_name = str(template.get("name", "Item")).strip() or "Item"
        display_name = base_name if infinite else f"{base_name} [{quantity}]"
        entries.append({
            "source": "template",
            "stock_entry": stock_entry,
            "template_id": str(template.get("template_id", template_id)).strip(),
            "template": template,
            "template_kind": template_kind,
            "name": display_name,
            "base_name": base_name,
            "keywords": [str(keyword).strip().lower() for keyword in template.get("keywords", []) if str(keyword).strip()],
            "price": _get_merchant_buy_price(merchant, template, template_kind=template_kind),
            "quantity": quantity,
            "infinite": infinite,
        })

    resale_items = getattr(merchant, "merchant_resale_items", {}) or {}
    for stack_key, resale_stack in resale_items.items():
        if not isinstance(resale_stack, dict):
            continue

        stack_items = resale_stack.get("items", [])
        if not isinstance(stack_items, list) or not stack_items:
            continue

        resale_item = stack_items[0]
        quantity = len(stack_items)
        template_kind = "Gear" if is_item_equippable(resale_item) else "Item"
        base_name = str(getattr(resale_item, "name", "Item")).strip() or "Item"
        entries.append({
            "source": "resale",
            "stack_key": stack_key,
            "item": resale_item,
            "template_id": str(getattr(resale_item, "template_id", "")).strip(),
            "template": None,
            "template_kind": template_kind,
            "name": f"{base_name} [{quantity}]",
            "base_name": base_name,
            "keywords": [str(keyword).strip().lower() for keyword in resale_item.keywords if str(keyword).strip()],
            "price": _get_merchant_resale_price(merchant, resale_item),
            "quantity": quantity,
            "infinite": False,
        })

    return entries


def _resolve_merchant_stock_selector(merchant, selector: str):
    requested_index, selector_parts, parse_error = _parse_trade_selector(selector)
    if parse_error is not None:
        return None, parse_error

    matches = []
    for entry in _build_merchant_stock_entries(merchant):
        keywords = _tokenize_selector_value(str(entry.get("base_name", entry["name"])))
        keywords.update(_tokenize_selector_value(str(entry["template_id"])))
        entry_keywords = entry.get("keywords", [])
        if not isinstance(entry_keywords, list):
            entry_keywords = []
        keywords.update(_tokenize_selector_value(" ".join(str(keyword) for keyword in entry_keywords)))
        if all(keyword in keywords for keyword in selector_parts):
            matches.append(entry)

    if not matches:
        return None, f"{selector} is not sold here."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} matching stock item(s) found for '{selector}'."
        return matches[requested_index - 1], None

    return matches[0], None


def _build_inventory_item_from_template(template: dict) -> ItemState:
    if str(template.get("slot", "")).strip().lower() in {"weapon", "armor"}:
        return build_equippable_item_from_template(template)

    return ItemState(
        item_id=f"item-{uuid.uuid4().hex[:8]}",
        template_id=str(template.get("template_id", "")).strip(),
        name=str(template.get("name", "Item")).strip() or "Item",
        description=str(template.get("description", "")),
        keywords=[str(keyword).strip().lower() for keyword in template.get("keywords", []) if str(keyword).strip()],
    )


def _resolve_owned_trade_item(session: ClientSession, selector: str):
    from targeting_items import _resolve_inventory_selector

    inventory_item, inventory_error = _resolve_inventory_selector(session, selector)
    if inventory_item is not None:
        return inventory_item, None

    return None, inventory_error or f"{selector} doesn't exist in your inventory."


def _remove_owned_trade_item(session: ClientSession, item: ItemState) -> None:
    if item.item_id in session.inventory_items:
        session.inventory_items.pop(item.item_id, None)
        return

    if item.item_id in session.equipment.equipped_items:
        unequip_item(session, item)
        session.inventory_items.pop(item.item_id, None)


def _display_merchant_stock(session: ClientSession, merchant) -> OutboundMessage:
    stock_entries = _build_merchant_stock_entries(merchant)
    rows = [
        [
            str(entry["name"]),
            str(entry["template_kind"]),
            f"{_as_int(entry.get('price', 0))} coins",
        ]
        for entry in stock_entries
    ]
    row_cell_colors = [
        [
            "bright_magenta" if str(entry.get("template_kind", "")).strip().lower() == "gear" else "bright_yellow",
            "bright_cyan",
            "bright_yellow",
        ]
        for entry in stock_entries
    ]
    title = f"{merchant.name}'s Wares"
    parts = build_menu_table_parts(
        title,
        ["Item", "Type", "Price"],
        rows,
        column_colors=["bright_magenta", "bright_cyan", "bright_yellow"],
        row_cell_colors=row_cell_colors,
        column_alignments=["left", "left", "right"],
        empty_message="Nothing is for sale right now.",
    )
    parts.extend([
        newline_part(),
        build_part("Commands: ", "bright_white"),
        build_part("buy <item>", "bright_yellow", True),
        build_part(", ", "bright_white"),
        build_part("sell <item>", "bright_yellow", True),
        build_part(", ", "bright_white"),
        build_part("val <item>", "bright_yellow", True),
    ])
    return display_command_result(session, parts)
