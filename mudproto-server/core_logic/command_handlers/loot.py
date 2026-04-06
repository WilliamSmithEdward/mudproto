from display_core import build_part
from display_feedback import display_command_result, display_error
from item_logic import _build_corpse_label, _build_item_reference_parts
from models import ClientSession
from targeting_entities import list_room_corpses, resolve_corpse_item_selector, resolve_room_corpse_selector
from targeting_items import _list_room_ground_items, _pickup_ground_item, _resolve_room_ground_matches

from .runtime import OutboundResult


HandledResult = OutboundResult | None


def handle_loot_command(
    session: ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb != "get":
        return None

    if len(args) == 1:
        single_selector = args[0].strip()
        normalized_selector = single_selector.lower()

        if normalized_selector.startswith("all.") and len(single_selector) > 4:
            item_selector = single_selector[4:]
            room_id = session.player.current_room_id
            matches, _, selector_error = _resolve_room_ground_matches(session, room_id, item_selector)
            if selector_error is not None:
                return display_error(selector_error, session)

            for item in matches:
                _pickup_ground_item(session, room_id, item)

            parts = [
                build_part("You take all matching items from the room.", "bright_white"),
            ]
            for item in matches:
                parts.extend([
                    build_part("\n"),
                    build_part("You take ", "bright_white"),
                    *_build_item_reference_parts(item),
                    build_part(".", "bright_white"),
                ])
            return display_command_result(session, parts)

        if normalized_selector not in {"coin", "coins", "all"}:
            room_id = session.player.current_room_id
            matches, requested_index, selector_error = _resolve_room_ground_matches(session, room_id, single_selector)
            if selector_error is None:
                selected_item = matches[0] if requested_index is None else (
                    matches[requested_index - 1] if requested_index <= len(matches) else None
                )
                if selected_item is None:
                    return display_error(
                        f"Only {len(matches)} match(es) found for '{single_selector}'.",
                        session,
                    )

                _pickup_ground_item(session, room_id, selected_item)
                return display_command_result(session, [
                    build_part("You take ", "bright_white"),
                    *_build_item_reference_parts(selected_item),
                    build_part(".", "bright_white"),
                ])

    if len(args) == 1 and args[0].strip().lower() in {"coin", "coins"}:
        room_id = session.player.current_room_id
        room_coin_pile = max(0, int(session.room_coin_piles.get(room_id, 0)))
        if room_coin_pile <= 0:
            return display_error("There are no coins on the ground.", session)

        session.room_coin_piles[room_id] = 0
        session.status.coins += room_coin_pile
        return display_command_result(session, [
            build_part("You take ", "bright_white"),
            build_part(str(room_coin_pile), "bright_cyan", True),
            build_part(" coins from the room.", "bright_white"),
        ])

    if len(args) == 1 and args[0].strip().lower() == "all":
        corpses = list_room_corpses(session, session.player.current_room_id)
        room_id = session.player.current_room_id
        room_items = _list_room_ground_items(session, room_id)
        room_coin_pile = max(0, int(session.room_coin_piles.get(room_id, 0)))
        if not corpses and room_coin_pile <= 0 and not room_items:
            return display_error("There is nothing to loot in this room.", session)

        total_coins = room_coin_pile
        looted_items = []

        if room_coin_pile > 0:
            session.room_coin_piles[room_id] = 0

        for item in room_items:
            _pickup_ground_item(session, room_id, item)
            looted_items.append(item)

        for corpse in corpses:
            corpse_coins = max(0, corpse.coins)
            total_coins += corpse_coins
            corpse.coins = 0

            corpse_items = list(corpse.loot_items.values())
            corpse_items.sort(key=lambda item: item.name.lower())
            for item in corpse_items:
                session.inventory_items[item.item_id] = item
                corpse.loot_items.pop(item.item_id, None)
                looted_items.append(item)

        if total_coins <= 0 and not looted_items:
            return display_error("There is nothing to loot in this room.", session)

        session.status.coins += total_coins

        parts = [
            build_part("You loot everything in the room.", "bright_white"),
        ]
        if total_coins > 0:
            parts.extend([
                build_part("\n"),
                build_part("Coins +", "bright_white"),
                build_part(str(total_coins), "bright_cyan", True),
            ])
        for item in looted_items:
            parts.extend([
                build_part("\n"),
                build_part("You take ", "bright_white"),
                *_build_item_reference_parts(item),
                build_part(".", "bright_white"),
            ])

        return display_command_result(session, parts)

    if len(args) < 2:
        return display_error("Usage: get <item|all|coins> <corpse selector>", session)

    corpse_selector = args[-1].strip()

    item_selector = " ".join(args[:-1]).strip()
    if not item_selector:
        return display_error("Usage: get <item|all|coins> <corpse selector>", session)

    corpse, resolve_error = resolve_room_corpse_selector(
        session,
        session.player.current_room_id,
        corpse_selector,
    )
    if corpse is None:
        return display_error(resolve_error or f"No corpse matching '{corpse_selector}' is here.", session)

    normalized_item_selector = item_selector.lower()

    if normalized_item_selector == "all":
        taken_coins = max(0, corpse.coins)
        taken_items = list(corpse.loot_items.values())
        taken_items.sort(key=lambda item: item.name.lower())

        if taken_coins <= 0 and not taken_items:
            return display_error("There is nothing to loot from that corpse.", session)

        corpse.coins = 0
        if taken_coins > 0:
            session.status.coins += taken_coins

        for item in taken_items:
            session.inventory_items[item.item_id] = item
            corpse.loot_items.pop(item.item_id, None)

        parts = [
            build_part("You loot ", "bright_white"),
            build_part(_build_corpse_label(corpse.source_name), "bright_yellow", True),
            build_part(".", "bright_white"),
        ]
        if taken_coins > 0:
            parts.extend([
                build_part("\n"),
                build_part("Coins +", "bright_white"),
                build_part(str(taken_coins), "bright_cyan", True),
            ])
        for item in taken_items:
            parts.extend([
                build_part("\n"),
                build_part("You take ", "bright_white"),
                *_build_item_reference_parts(item),
                build_part(".", "bright_white"),
            ])

        return display_command_result(session, parts)

    if normalized_item_selector in {"coin", "coins"}:
        if corpse.coins <= 0:
            return display_error("That corpse has no coins left.", session)

        taken_coins = corpse.coins
        corpse.coins = 0
        session.status.coins += taken_coins
        return display_command_result(session, [
            build_part("You take ", "bright_white"),
            build_part(str(taken_coins), "bright_cyan", True),
            build_part(" coins from ", "bright_white"),
            build_part(_build_corpse_label(corpse.source_name), "bright_yellow", True),
            build_part(".", "bright_white"),
        ])

    item, item_error = resolve_corpse_item_selector(corpse, item_selector)
    if item is None:
        return display_error(item_error or f"No item matching '{item_selector}' is on that corpse.", session)

    corpse.loot_items.pop(item.item_id, None)
    session.inventory_items[item.item_id] = item

    return display_command_result(session, [
        build_part("You take ", "bright_white"),
        *_build_item_reference_parts(item),
        build_part(" from ", "bright_white"),
        build_part(_build_corpse_label(corpse.source_name), "bright_yellow", True),
        build_part(".", "bright_white"),
    ])
