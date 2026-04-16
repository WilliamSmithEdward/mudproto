from display_core import build_part
from display_feedback import display_command_result, display_error
from item_logic import _build_item_reference_parts
from models import ClientSession
import commerce as _commerce

from .types import OutboundResult

_build_inventory_item_from_template = getattr(_commerce, "_build_inventory_item_from_template")
_display_merchant_stock = getattr(_commerce, "_display_merchant_stock")
_get_merchant_sale_offer = getattr(_commerce, "_get_merchant_sale_offer")
_remove_owned_trade_item = getattr(_commerce, "_remove_owned_trade_item")
_resolve_merchant_stock_selector = getattr(_commerce, "_resolve_merchant_stock_selector")
_resolve_owned_trade_item = getattr(_commerce, "_resolve_owned_trade_item")
_resolve_room_merchant = getattr(_commerce, "_resolve_room_merchant")
_append_item_to_merchant_stock = getattr(_commerce, "_append_item_to_merchant_stock")


HandledResult = OutboundResult | None


def handle_commerce_command(
    session: ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb in {"list", "li", "lis"}:
        merchant, resolve_error = _resolve_room_merchant(session)
        if merchant is None:
            return display_error(
                resolve_error or "There is no merchant here.",
                session,
                error_code="no-merchant-here",
            )
        return _display_merchant_stock(session, merchant)

    if verb == "buy":
        merchant, resolve_error = _resolve_room_merchant(session)
        if merchant is None:
            return display_error(
                resolve_error or "There is no merchant here.",
                session,
                error_code="no-merchant-here",
            )

        selector = ".".join(arg.strip().lower() for arg in args if arg.strip())
        if not selector:
            return display_error(
                "Usage: buy <item>",
                session,
                error_code="usage",
                error_context={"usage": "buy <item>"},
            )

        stock_entry, stock_error = _resolve_merchant_stock_selector(merchant, selector)
        if stock_entry is None:
            return display_error(
                stock_error or f"{selector} is not sold here.",
                session,
                error_code="merchant-item-unavailable",
                error_context={"target": selector},
            )

        item_name = str(stock_entry["name"]).strip() or "Item"
        price = int(stock_entry["price"])
        if session.status.coins < price:
            return display_error(
                f"You need {price} coins to buy {item_name}.",
                session,
                error_code="merchant-insufficient-coins",
                error_context={"item": item_name, "price": price},
            )

        if str(stock_entry.get("source", "template")).strip().lower() == "resale":
            resale_items = getattr(merchant, "merchant_resale_items", {}) or {}
            stack_key = str(stock_entry.get("stack_key", "")).strip()
            resale_stack = resale_items.get(stack_key)
            if not isinstance(resale_stack, dict):
                return display_error(
                    f"{item_name} is no longer available.",
                    session,
                    error_code="merchant-item-unavailable",
                    error_context={"item": item_name},
                )

            stack_items = resale_stack.get("items", [])
            if not isinstance(stack_items, list) or not stack_items:
                resale_items.pop(stack_key, None)
                return display_error(
                    f"{item_name} is no longer available.",
                    session,
                    error_code="merchant-item-unavailable",
                    error_context={"item": item_name},
                )

            purchased_item = stack_items.pop(0)
            if not stack_items:
                resale_items.pop(stack_key, None)
        else:
            stock_entry_ref = stock_entry.get("stock_entry")
            if not isinstance(stock_entry_ref, dict):
                return display_error(
                    f"{item_name} is no longer available.",
                    session,
                    error_code="merchant-item-unavailable",
                    error_context={"item": item_name},
                )

            if not bool(stock_entry_ref.get("infinite", False)):
                available_quantity = max(0, int(stock_entry_ref.get("quantity", 0)))
                if available_quantity <= 0:
                    return display_error(
                        f"{item_name} is out of stock.",
                        session,
                        error_code="merchant-out-of-stock",
                        error_context={"item": item_name},
                    )
                stock_entry_ref["quantity"] = available_quantity - 1

            purchased_item = _build_inventory_item_from_template(stock_entry["template"])

        session.status.coins -= price
        session.inventory_items[purchased_item.item_id] = purchased_item

        return display_command_result(session, [
            build_part("You buy ", "feedback.text"),
            *_build_item_reference_parts(purchased_item),
            build_part(" for ", "feedback.text"),
            build_part(f"{price} coins", "feedback.value", True),
            build_part(".", "feedback.text"),
        ])

    if verb == "sell":
        merchant, resolve_error = _resolve_room_merchant(session)
        if merchant is None:
            return display_error(
                resolve_error or "There is no merchant here.",
                session,
                error_code="no-merchant-here",
            )

        selector = ".".join(arg.strip().lower() for arg in args if arg.strip())
        if not selector:
            return display_error(
                "Usage: sell <item>",
                session,
                error_code="usage",
                error_context={"usage": "sell <item>"},
            )

        owned_item, item_error = _resolve_owned_trade_item(session, selector)
        if owned_item is None:
            return display_error(
                item_error or f"{selector} doesn't exist in your inventory.",
                session,
                error_code="merchant-not-carrying",
                error_context={"target": selector},
            )

        offer = _get_merchant_sale_offer(merchant, owned_item)
        _remove_owned_trade_item(session, owned_item)
        _append_item_to_merchant_stock(merchant, owned_item)
        session.status.coins += offer

        return display_command_result(session, [
            build_part(merchant.name, "feedback.value", True),
            build_part(" buys ", "feedback.text"),
            *_build_item_reference_parts(owned_item),
            build_part(" for ", "feedback.text"),
            build_part(f"{offer} coins", "feedback.warning", True),
            build_part(".", "feedback.text"),
        ])

    if verb in {"val", "value"}:
        merchant, resolve_error = _resolve_room_merchant(session)
        if merchant is None:
            return display_error(
                resolve_error or "There is no merchant here.",
                session,
                error_code="no-merchant-here",
            )

        selector = ".".join(arg.strip().lower() for arg in args if arg.strip())
        if not selector:
            return display_error(
                "Usage: val <item>",
                session,
                error_code="usage",
                error_context={"usage": "val <item>"},
            )

        owned_item, item_error = _resolve_owned_trade_item(session, selector)
        if owned_item is None:
            return display_error(
                item_error or f"{selector} doesn't exist in your inventory.",
                session,
                error_code="merchant-not-carrying",
                error_context={"target": selector},
            )

        offer = _get_merchant_sale_offer(merchant, owned_item)
        return display_command_result(session, [
            build_part(merchant.name, "feedback.value", True),
            build_part(" offers ", "feedback.text"),
            build_part(f"{offer} coins", "feedback.warning", True),
            build_part(" for ", "feedback.text"),
            *_build_item_reference_parts(owned_item),
            build_part(".", "feedback.text"),
        ])

    return None
