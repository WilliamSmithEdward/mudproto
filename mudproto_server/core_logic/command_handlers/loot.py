from containers import (
    can_pick_up_item,
    resolve_accessible_container,
    split_item_and_container_selectors,
    take_all_from_container,
    take_item_from_container,
)
from display_core import build_part, newline_part
from display_feedback import display_command_result, display_error
from item_logic import _build_item_reference_parts
from models import ClientSession
from targeting_items import _list_room_ground_items, _pickup_ground_item, _resolve_room_ground_matches

from .types import OutboundResult


HandledResult = OutboundResult | None


def _pickup_room_item(session: ClientSession, room_id: str, item):
    can_take, take_error = can_pick_up_item(item)
    if not can_take:
        return False, take_error or f"The {item.name} is fixed in place."

    _pickup_ground_item(session, room_id, item)
    return True, None


def handle_loot_command(
    session: ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb != "get":
        return None

    room_id = session.player.current_room_id
    joined_selector = " ".join(arg.strip() for arg in args if arg.strip()).strip()
    normalized_joined_selector = joined_selector.lower()

    if len(args) >= 2:
        item_selector, container_selector, _ = split_item_and_container_selectors(session, args)
        if item_selector and container_selector:
            container, _, _ = resolve_accessible_container(session, container_selector)
            if container is not None:
                if item_selector.strip().lower() == "all":
                    return take_all_from_container(session, container)
                return take_item_from_container(session, container, item_selector)

    if (
        joined_selector
        and normalized_joined_selector not in {"coin", "coins", "all"}
        and not normalized_joined_selector.startswith("all.")
    ):
        matches, requested_index, selector_error = _resolve_room_ground_matches(session, room_id, joined_selector)
        if selector_error is None:
            selected_item = matches[0] if requested_index is None else (
                matches[requested_index - 1] if requested_index <= len(matches) else None
            )
            if selected_item is None:
                return display_error(
                    f"Only {len(matches)} match(es) found for '{joined_selector}'.",
                    session,
                )

            picked_up, pickup_error = _pickup_room_item(session, room_id, selected_item)
            if not picked_up:
                return display_error(pickup_error or f"You cannot take {selected_item.name}.", session)

            return display_command_result(session, [
                build_part("You take ", "feedback.text"),
                *_build_item_reference_parts(selected_item),
                build_part(".", "feedback.text"),
            ])

    if len(args) == 1:
        single_selector = args[0].strip()
        normalized_selector = single_selector.lower()

        if normalized_selector.startswith("all.") and len(single_selector) > 4:
            item_selector = single_selector[4:]
            matches, _, selector_error = _resolve_room_ground_matches(session, room_id, item_selector)
            if selector_error is not None:
                return display_error(selector_error, session)

            portable_matches = []
            blocked_errors: list[str] = []
            for item in matches:
                picked_up, pickup_error = _pickup_room_item(session, room_id, item)
                if picked_up:
                    portable_matches.append(item)
                elif pickup_error:
                    blocked_errors.append(pickup_error)

            if not portable_matches:
                return display_error(blocked_errors[0] if blocked_errors else f"No room item matches '{item_selector}'.", session)

            parts = [
                build_part("You take all matching items from the room.", "feedback.text"),
            ]
            for item in portable_matches:
                parts.extend([
                    newline_part(),
                    build_part("You take ", "feedback.text"),
                    *_build_item_reference_parts(item),
                    build_part(".", "feedback.text"),
                ])
            return display_command_result(session, parts)

    if len(args) == 1 and args[0].strip().lower() in {"coin", "coins"}:
        room_coin_pile = max(0, int(session.room_coin_piles.get(room_id, 0)))
        if room_coin_pile <= 0:
            return display_error(
                "There are no coins on the ground.",
                session,
                error_code="no-ground-coins",
            )

        session.room_coin_piles[room_id] = 0
        session.status.coins += room_coin_pile
        return display_command_result(session, [
            build_part("You take ", "feedback.text"),
            build_part(str(room_coin_pile), "feedback.value", True),
            build_part(" coins from the room.", "feedback.text"),
        ])

    if len(args) == 1 and args[0].strip().lower() == "all":
        room_items = _list_room_ground_items(session, room_id)
        room_coin_pile = max(0, int(session.room_coin_piles.get(room_id, 0)))
        if room_coin_pile <= 0 and not room_items:
            return display_error("There is nothing to loot in this room.", session)

        total_coins = room_coin_pile
        looted_items = []
        blocked_errors: list[str] = []

        if room_coin_pile > 0:
            session.room_coin_piles[room_id] = 0

        for item in room_items:
            picked_up, pickup_error = _pickup_room_item(session, room_id, item)
            if picked_up:
                looted_items.append(item)
            elif pickup_error:
                blocked_errors.append(pickup_error)

        if total_coins > 0:
            session.status.coins += total_coins

        if total_coins <= 0 and not looted_items:
            return display_error(blocked_errors[0] if blocked_errors else "There is nothing to loot in this room.", session)

        parts = [
            build_part("You gather up the loose items in the room.", "feedback.text"),
        ]
        if total_coins > 0:
            parts.extend([
                newline_part(),
                build_part("Coins +", "feedback.text"),
                build_part(str(total_coins), "feedback.value", True),
            ])
        for item in looted_items:
            parts.extend([
                newline_part(),
                build_part("You take ", "bright_white"),
                *_build_item_reference_parts(item),
                build_part(".", "bright_white"),
            ])
        if blocked_errors:
            parts.extend([
                newline_part(),
                build_part("Some larger containers remain where they are.", "feedback.muted"),
            ])

        return display_command_result(session, parts)

    if len(args) < 2:
        return display_error(
            "Usage: get <item|all|coins> [container]",
            session,
            error_code="usage",
            error_context={"usage": "get <item|all|coins> [container]"},
        )

    return display_error("No accessible container matches that command.", session)
