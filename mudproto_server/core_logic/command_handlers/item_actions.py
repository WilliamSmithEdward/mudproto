import re

from containers import put_item_into_container, resolve_accessible_container, split_item_and_container_selectors
from display_core import build_part, newline_part
from display_feedback import display_command_result, display_error
from item_logic import _build_item_reference_parts, _item_highlight_color, _use_misc_item
from models import ClientSession
from targeting_items import _add_item_to_room_ground, _resolve_inventory_selector

from .types import OutboundResult


HandledResult = OutboundResult | None


def handle_item_drop_command(
    session: ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb in {"put", "pu"}:
        if len(args) < 2:
            return display_error("Usage: put <item> <container>", session)

        item_selector, container_selector, parse_error = split_item_and_container_selectors(session, args)
        if parse_error is not None or not item_selector or not container_selector:
            return display_error("Usage: put <item> <container>", session)

        container, _, container_error = resolve_accessible_container(session, container_selector)
        if container is None:
            return display_error(container_error or f"No container matching '{container_selector}' is here.", session)

        return put_item_into_container(session, item_selector, container)

    if verb not in {"drop", "dro", "dr"}:
        return None

    if not args:
        return display_error("Usage: drop <selector>", session)

    selector = ".".join(arg.strip().lower() for arg in args if arg.strip())
    if not selector:
        return display_error("Usage: drop <selector>", session)

    if selector.startswith("all.") and len(selector) > 4:
        item_selector = selector[4:]
        selector_tokens = {token for token in re.findall(r"[a-zA-Z0-9]+", item_selector) if token}
        if not selector_tokens:
            return display_error("Usage: drop all.<item>", session)

        inventory_matches = []
        for item in list(session.inventory_items.values()):
            item_keywords = {token for token in re.findall(r"[a-zA-Z0-9]+", item.name.lower()) if token}
            if selector_tokens.issubset(item_keywords):
                inventory_matches.append(item)

        if not inventory_matches:
            return display_error(f"No inventory item matches '{item_selector}'.", session)

        dropped_items = []
        for item in inventory_matches:
            session.inventory_items.pop(item.item_id, None)
            _add_item_to_room_ground(session, session.player.current_room_id, item)
            dropped_items.append(item)

        parts = [
            build_part("You drop all matching items.", "bright_white"),
        ]
        for item in dropped_items:
            parts.extend([
                newline_part(),
                build_part(" - ", "bright_white"),
                build_part(item.name, _item_highlight_color(item), True),
            ])
        return display_command_result(session, parts)

    coin_drop_match = re.match(r"^(\d+)\*coins?$", selector)
    if coin_drop_match is not None:
        drop_amount = int(coin_drop_match.group(1))
        if drop_amount <= 0:
            return display_error("Coin drop amount must be greater than zero.", session)
        if session.status.coins < drop_amount:
            return display_error(
                f"You only have {session.status.coins} coins.",
                session,
            )

        session.status.coins -= drop_amount
        room_id = session.player.current_room_id
        existing_pile = max(0, int(session.room_coin_piles.get(room_id, 0)))
        session.room_coin_piles[room_id] = existing_pile + drop_amount
        return display_command_result(session, [
            build_part("You drop ", "bright_white"),
            build_part(str(drop_amount), "bright_cyan", True),
            build_part(" coins into a pile on the ground.", "bright_white"),
        ])

    if selector == "all":
        inventory_items = list(session.inventory_items.values())

        if not inventory_items:
            return display_error("You have nothing to drop.", session)

        dropped_count = 0
        for item in inventory_items:
            session.inventory_items.pop(item.item_id, None)
            _add_item_to_room_ground(session, session.player.current_room_id, item)
            dropped_count += 1

        return display_command_result(session, [
            build_part("You drop all carried items.", "bright_white"),
            newline_part(),
            build_part("Items dropped: ", "bright_white"),
            build_part(str(dropped_count), "bright_yellow", True),
        ])

    inventory_item, inventory_error = _resolve_inventory_selector(session, selector)
    if inventory_item is not None:
        session.inventory_items.pop(inventory_item.item_id, None)
        _add_item_to_room_ground(session, session.player.current_room_id, inventory_item)
        return display_command_result(session, [
            build_part("You drop ", "bright_white"),
            *_build_item_reference_parts(inventory_item),
            build_part(".", "bright_white"),
        ])

    return display_error(inventory_error or "Unable to resolve inventory selector.", session)


def handle_item_use_command(
    session: ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb != "use":
        return None

    selector = ".".join(arg.strip().lower() for arg in args if arg.strip())
    return _use_misc_item(session, selector)
