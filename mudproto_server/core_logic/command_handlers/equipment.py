import re

from display_character import display_equipment
from display_core import build_part, newline_part
from display_feedback import display_command_result, display_error
from equipment_logic import (
    HAND_BOTH,
    HAND_MAIN,
    HAND_OFF,
    equip_item,
    get_equipped_main_hand,
    get_equipped_off_hand,
    list_worn_items,
    resolve_equipped_selector,
    unequip_item,
    wear_item,
)
from inventory import is_item_equippable, resolve_equipment_selector
from item_logic import _build_item_reference_parts, _item_highlight_color
from models import ClientSession
from targeting_items import _resolve_inventory_selector, _resolve_wear_inventory_selector
from targeting_parsing import _parse_hand_and_selector, _parse_wear_selector_and_location

from .types import OutboundResult


HandledResult = OutboundResult | None


def handle_equipment_command(
    session: ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb == "equip":
        if not args:
            return display_equipment(session)

        hand, selector, parse_error = _parse_hand_and_selector(args)
        if parse_error is not None or selector is None:
            return display_error(
                parse_error or "Usage: equip <selector> [main|off|both]",
                session,
                error_code="usage",
                error_context={"usage": "equip <selector> [main|off|both]"},
            )

        item, resolve_error = resolve_equipment_selector(session, selector)
        if item is None:
            inventory_item, _inventory_error = _resolve_inventory_selector(session, selector)
            if inventory_item is not None:
                return display_error(
                    f"{inventory_item.name} cannot be equipped.",
                    session,
                    error_code="item-not-equippable",
                    error_context={"item": inventory_item.name},
                )
            return display_error(resolve_error or "Unable to resolve equipment selector.", session)

        equipped, equip_result = equip_item(session, item, hand)
        if not equipped:
            return display_error(equip_result, session)

        if equip_result == HAND_BOTH:
            return display_command_result(session, [
                build_part("You equip ", "feedback.text"),
                *_build_item_reference_parts(item),
                build_part(" with both hands.", "feedback.text"),
            ])

        hand_label = "main hand" if equip_result == HAND_MAIN else "off hand"
        return display_command_result(session, [
            build_part("You equip ", "feedback.text"),
            *_build_item_reference_parts(item),
            build_part(" in your ", "feedback.text"),
            build_part(hand_label, "feedback.warning", True),
            build_part(".", "feedback.text"),
        ])

    if verb in {"wield", "wiel", "wie", "wi"}:
        if not args:
            return display_error(
                "Usage: wield <selector> [main|both]",
                session,
                error_code="usage",
                error_context={"usage": "wield <selector> [main|both]"},
            )

        hand, selector, parse_error = _parse_hand_and_selector(args)
        if parse_error is not None or selector is None:
            return display_error(
                "Usage: wield <selector> [main|both]",
                session,
                error_code="usage",
                error_context={"usage": "wield <selector> [main|both]"},
            )
        if hand == HAND_OFF:
            return display_error("Use hold <selector> for your off hand.", session)

        item, resolve_error = resolve_equipment_selector(session, selector)
        if item is None:
            inventory_item, inventory_error = _resolve_inventory_selector(session, selector)
            if inventory_item is None:
                return display_error(resolve_error or inventory_error or "Unable to resolve equipment selector.", session)
            return display_error(
                f"{inventory_item.name} cannot be wielded.",
                session,
                error_code="item-not-wieldable",
                error_context={"item": inventory_item.name},
            )

        current_main = get_equipped_main_hand(session)
        current_off = get_equipped_off_hand(session)
        requested_hand = hand or HAND_MAIN
        if requested_hand == HAND_BOTH or bool(getattr(item, "requires_two_hands", False)):
            if current_main is not None and current_main.item_id != item.item_id:
                return display_error(
                    f"Your main hand is already occupied by {current_main.name}. Remove it first.",
                    session,
                )
            if current_off is not None and current_off.item_id != item.item_id:
                return display_error(
                    f"Your off hand is already occupied by {current_off.name}. Remove it first.",
                    session,
                )
        elif current_main is not None and current_main.item_id != item.item_id:
            return display_error(
                f"Your main hand is already occupied by {current_main.name}. Remove it first.",
                session,
            )

        equipped, equip_result = equip_item(session, item, hand or HAND_MAIN)
        if not equipped:
            return display_error(equip_result, session)

        if equip_result == HAND_BOTH:
            return display_command_result(session, [
                build_part("You wield ", "feedback.text"),
                *_build_item_reference_parts(item),
                build_part(" with both hands.", "feedback.text"),
            ])

        return display_command_result(session, [
            build_part("You wield ", "feedback.text"),
            *_build_item_reference_parts(item),
            build_part(".", "feedback.text"),
        ])

    if verb in {"hold", "hol", "ho"}:
        if not args:
            return display_error(
                "Usage: hold <selector>",
                session,
                error_code="usage",
                error_context={"usage": "hold <selector>"},
            )

        selector = ".".join(arg.strip().lower() for arg in args if arg.strip())
        item, resolve_error = resolve_equipment_selector(session, selector)
        if item is None:
            inventory_item, inventory_error = _resolve_inventory_selector(session, selector)
            if inventory_item is None:
                return display_error(resolve_error or inventory_error or "Unable to resolve equipment selector.", session)
            return display_error(
                f"{inventory_item.name} cannot be held.",
                session,
                error_code="item-not-holdable",
                error_context={"item": inventory_item.name},
            )

        current_off = get_equipped_off_hand(session)
        if current_off is not None:
            return display_error(
                f"Your off hand is already occupied by {current_off.name}. Remove it first.",
                session,
            )

        equipped, equip_result = equip_item(session, item, HAND_OFF)
        if not equipped:
            return display_error(equip_result, session)

        return display_command_result(session, [
            build_part("You hold ", "feedback.text"),
            *_build_item_reference_parts(item),
            build_part(" in your off hand.", "feedback.text"),
        ])

    if verb in {"wear", "wea", "puton"}:
        if not args:
            return display_error(
                "Usage: wear <selector> [location]",
                session,
                error_code="usage",
                error_context={"usage": "wear <selector> [location]"},
            )

        selector, wear_location, parse_error = _parse_wear_selector_and_location(args)
        if parse_error is not None or selector is None:
            return display_error(
                parse_error or "Usage: wear <selector> [location]",
                session,
                error_code="usage",
                error_context={"usage": "wear <selector> [location]"},
            )

        if selector.startswith("all.") and len(selector) > 4:
            item_selector = selector[4:]
            selector_tokens = {token for token in re.findall(r"[a-zA-Z0-9]+", item_selector) if token}
            if not selector_tokens:
                return display_error(
                    "Usage: wear all.<item>",
                    session,
                    error_code="usage",
                    error_context={"usage": "wear all.<item>"},
                )

            wearable_items = []

            for inventory_item in list(session.inventory_items.values()):
                item_keywords = {token for token in re.findall(r"[a-zA-Z0-9]+", inventory_item.name.lower()) if token}
                if not selector_tokens.issubset(item_keywords):
                    continue

                if not is_item_equippable(inventory_item) or inventory_item.slot.strip().lower() != "armor":
                    continue
                wearable_items.append(inventory_item)

            wearable_items.sort(key=lambda item: (len(item.wear_slots) if item.wear_slots else 1, item.name.lower(), item.item_id))

            if not wearable_items:
                return display_error(f"No wearable inventory item matches '{item_selector}'.", session)

            worn_results: list[tuple[str, str]] = []
            for item in wearable_items:
                worn, wear_result = wear_item(session, item)
                if worn:
                    worn_results.append((item.name, wear_result))

            if not worn_results:
                return display_error("You cannot wear any additional matching items right now.", session)

            parts = [
                build_part("You wear all matching items.", "feedback.text"),
            ]
            for item_name, slot_name in worn_results:
                parts.extend([
                    newline_part(),
                    build_part(" - ", "feedback.text"),
                    build_part(item_name, "feedback.value", True),
                    build_part(" on your ", "feedback.text"),
                    build_part(slot_name, "feedback.warning", True),
                    build_part(".", "feedback.text"),
                ])

            return display_command_result(session, parts)

        if selector == "all":
            wearable_items = []
            for inventory_item in list(session.inventory_items.values()):
                if is_item_equippable(inventory_item) and inventory_item.slot.strip().lower() == "armor":
                    wearable_items.append(inventory_item)

            wearable_items.sort(key=lambda item: (len(item.wear_slots) if item.wear_slots else 1, item.name.lower(), item.item_id))

            if not wearable_items:
                return display_error("You have nothing wearable in your inventory.", session)

            worn_results: list[tuple[str, str]] = []
            for item in wearable_items:
                worn, wear_result = wear_item(session, item)
                if worn:
                    worn_results.append((item.name, wear_result))

            if not worn_results:
                return display_error("You cannot wear any additional items right now.", session)

            parts = [
                build_part("You wear everything you can.", "feedback.text"),
            ]
            for item_name, slot_name in worn_results:
                parts.extend([
                    newline_part(),
                    build_part(" - ", "feedback.text"),
                    build_part(item_name, "feedback.value", True),
                    build_part(" on your ", "feedback.text"),
                    build_part(slot_name, "feedback.warning", True),
                    build_part(".", "feedback.text"),
                ])

            return display_command_result(session, parts)

        item, resolve_error = _resolve_wear_inventory_selector(session, selector)
        if resolve_error is not None or item is None:
            return display_error(resolve_error or "Unable to resolve inventory selector.", session)

        if item.slot.strip().lower() != "armor":
            return display_error(
                f"{item.name} cannot be worn.",
                session,
                error_code="item-not-wearable",
                error_context={"item": item.name},
            )

        worn, wear_result = wear_item(session, item, wear_location)
        if not worn:
            return display_error(wear_result, session)

        return display_command_result(session, [
            build_part("You wear ", "feedback.text"),
            *_build_item_reference_parts(item),
            build_part(" on your ", "feedback.text"),
            build_part(wear_result, "feedback.warning", True),
            build_part(".", "feedback.text"),
        ])

    if verb in {"remove", "rem"}:
        if not args:
            return display_error(
                "Usage: rem <selector>",
                session,
                error_code="usage",
                error_context={"usage": "rem <selector>"},
            )

        selector = ".".join(arg.strip().lower() for arg in args if arg.strip())
        if selector.startswith("all.") and len(selector) > 4:
            item_selector = selector[4:]
            selector_tokens = {token for token in re.findall(r"[a-zA-Z0-9]+", item_selector) if token}
            if not selector_tokens:
                return display_error(
                    "Usage: rem all.<item>",
                    session,
                    error_code="usage",
                    error_context={"usage": "rem all.<item>"},
                )

            worn_items = list_worn_items(session)
            matches = []
            seen_item_ids: set[str] = set()
            for _, worn_item in worn_items:
                if worn_item.item_id in seen_item_ids:
                    continue
                item_keywords = {token for token in re.findall(r"[a-zA-Z0-9]+", worn_item.name.lower()) if token}
                if selector_tokens.issubset(item_keywords):
                    matches.append(worn_item)
                seen_item_ids.add(worn_item.item_id)

            if not matches:
                return display_error(f"No equipped item matches '{item_selector}'.", session)

            removed_items = []
            for worn_item in matches:
                if unequip_item(session, worn_item):
                    removed_items.append(worn_item)

            if not removed_items:
                return display_error(f"No equipped item matches '{item_selector}'.", session)

            parts = [
                build_part("You remove all matching equipped items.", "feedback.text"),
            ]
            for item in removed_items:
                parts.extend([
                    newline_part(),
                    build_part(" - ", "feedback.text"),
                    build_part(item.name, _item_highlight_color(item), True),
                ])
            return display_command_result(session, parts)

        if selector == "all":
            worn_items = list_worn_items(session)
            if not worn_items:
                return display_error("You have nothing to remove.", session)

            removed_items = []
            seen_item_ids: set[str] = set()
            for _, worn_item in worn_items:
                if worn_item.item_id in seen_item_ids:
                    continue
                if unequip_item(session, worn_item):
                    removed_items.append(worn_item)
                seen_item_ids.add(worn_item.item_id)

            if not removed_items:
                return display_error("You have nothing to remove.", session)

            parts = [
                build_part("You remove all equipped items and place them in your inventory.", "feedback.text"),
            ]
            for item in removed_items:
                parts.extend([
                    newline_part(),
                    build_part(" - ", "feedback.text"),
                    build_part(item.name, _item_highlight_color(item), True),
                ])
            return display_command_result(session, parts)

        item, resolve_error = resolve_equipped_selector(session, selector)
        if resolve_error is not None or item is None:
            return display_error(resolve_error or "Unable to resolve equipped item selector.", session)

        was_equipped = unequip_item(session, item)
        if not was_equipped:
            return display_error(f"{item.name} is not currently worn or held.", session)

        return display_command_result(session, [
            build_part("You remove ", "feedback.text"),
            build_part(item.name, _item_highlight_color(item), True),
            build_part(" and place it in your inventory.", "feedback.text"),
        ])

    return None

