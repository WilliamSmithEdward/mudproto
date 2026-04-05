from . import shared as s


HandledResult = s.OutboundResult | None


def handle_equipment_command(
    session: s.ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb == "equip":
        if not args:
            return s.display_equipment(session)

        hand, selector, parse_error = s._parse_hand_and_selector(args)
        if parse_error is not None or selector is None:
            return s.display_error(parse_error or "Usage: equip <selector> [main|off|both]", session)

        item, resolve_error = s.resolve_equipment_selector(session, selector)
        if item is None:
            inventory_item, inventory_error = s._resolve_inventory_selector(session, selector)
            if inventory_item is not None:
                return s.display_error(f"{inventory_item.name} cannot be equipped.", session)
            return s.display_error(resolve_error or "Unable to resolve equipment selector.", session)

        equipped, equip_result = s.equip_item(session, item, hand)
        if not equipped:
            return s.display_error(equip_result, session)

        if equip_result == s.HAND_BOTH:
            return s.display_command_result(session, [
                s.build_part("You equip ", "bright_white"),
                *s._build_item_reference_parts(item),
                s.build_part(" with both hands.", "bright_white"),
            ])

        hand_label = "main hand" if equip_result == s.HAND_MAIN else "off hand"
        return s.display_command_result(session, [
            s.build_part("You equip ", "bright_white"),
            *s._build_item_reference_parts(item),
            s.build_part(" in your ", "bright_white"),
            s.build_part(hand_label, "bright_yellow", True),
            s.build_part(".", "bright_white"),
        ])

    if verb in {"wield", "wiel", "wie", "wi"}:
        if not args:
            return s.display_error("Usage: wield <selector> [main|both]", session)

        hand, selector, parse_error = s._parse_hand_and_selector(args)
        if parse_error is not None or selector is None:
            return s.display_error("Usage: wield <selector> [main|both]", session)
        if hand == s.HAND_OFF:
            return s.display_error("Use hold <selector> for your off hand.", session)

        item, resolve_error = s.resolve_equipment_selector(session, selector)
        if item is None:
            inventory_item, inventory_error = s._resolve_inventory_selector(session, selector)
            if inventory_item is None:
                return s.display_error(resolve_error or inventory_error or "Unable to resolve equipment selector.", session)
            return s.display_error(f"{inventory_item.name} cannot be wielded.", session)

        current_main = s.get_equipped_main_hand(session)
        current_off = s.get_equipped_off_hand(session)
        requested_hand = hand or s.HAND_MAIN
        if requested_hand == s.HAND_BOTH or bool(getattr(item, "requires_two_hands", False)):
            if current_main is not None and current_main.item_id != item.item_id:
                return s.display_error(
                    f"Your main hand is already occupied by {current_main.name}. Remove it first.",
                    session,
                )
            if current_off is not None and current_off.item_id != item.item_id:
                return s.display_error(
                    f"Your off hand is already occupied by {current_off.name}. Remove it first.",
                    session,
                )
        elif current_main is not None and current_main.item_id != item.item_id:
            return s.display_error(
                f"Your main hand is already occupied by {current_main.name}. Remove it first.",
                session,
            )

        equipped, equip_result = s.equip_item(session, item, hand or s.HAND_MAIN)
        if not equipped:
            return s.display_error(equip_result, session)

        if equip_result == s.HAND_BOTH:
            return s.display_command_result(session, [
                s.build_part("You wield ", "bright_white"),
                *s._build_item_reference_parts(item),
                s.build_part(" with both hands.", "bright_white"),
            ])

        return s.display_command_result(session, [
            s.build_part("You wield ", "bright_white"),
            *s._build_item_reference_parts(item),
            s.build_part(".", "bright_white"),
        ])

    if verb in {"hold", "hol", "ho"}:
        if not args:
            return s.display_error("Usage: hold <selector>", session)

        selector = ".".join(arg.strip().lower() for arg in args if arg.strip())
        item, resolve_error = s.resolve_equipment_selector(session, selector)
        if item is None:
            inventory_item, inventory_error = s._resolve_inventory_selector(session, selector)
            if inventory_item is None:
                return s.display_error(resolve_error or inventory_error or "Unable to resolve equipment selector.", session)
            return s.display_error(f"{inventory_item.name} cannot be held.", session)

        current_off = s.get_equipped_off_hand(session)
        if current_off is not None:
            return s.display_error(
                f"Your off hand is already occupied by {current_off.name}. Remove it first.",
                session,
            )

        equipped, equip_result = s.equip_item(session, item, s.HAND_OFF)
        if not equipped:
            return s.display_error(equip_result, session)

        return s.display_command_result(session, [
            s.build_part("You hold ", "bright_white"),
            *s._build_item_reference_parts(item),
            s.build_part(" in your off hand.", "bright_white"),
        ])

    if verb in {"wear", "wea", "puton"}:
        if not args:
            return s.display_error("Usage: wear <selector> [location]", session)

        selector, wear_location, parse_error = s._parse_wear_selector_and_location(args)
        if parse_error is not None or selector is None:
            return s.display_error(parse_error or "Usage: wear <selector> [location]", session)

        if selector.startswith("all.") and len(selector) > 4:
            item_selector = selector[4:]
            selector_tokens = {token for token in s.re.findall(r"[a-zA-Z0-9]+", item_selector) if token}
            if not selector_tokens:
                return s.display_error("Usage: wear all.<item>", session)

            wearable_items = []

            for inventory_item in list(session.inventory_items.values()):
                item_keywords = {token for token in s.re.findall(r"[a-zA-Z0-9]+", inventory_item.name.lower()) if token}
                if not selector_tokens.issubset(item_keywords):
                    continue

                if not s.is_item_equippable(inventory_item) or inventory_item.slot.strip().lower() != "armor":
                    continue
                wearable_items.append(inventory_item)

            wearable_items.sort(key=lambda item: (len(item.wear_slots) if item.wear_slots else 1, item.name.lower(), item.item_id))

            if not wearable_items:
                return s.display_error(f"No wearable inventory item matches '{item_selector}'.", session)

            worn_results: list[tuple[str, str]] = []
            for item in wearable_items:
                worn, wear_result = s.wear_item(session, item)
                if worn:
                    worn_results.append((item.name, wear_result))

            if not worn_results:
                return s.display_error("You cannot wear any additional matching items right now.", session)

            parts = [
                s.build_part("You wear all matching items.", "bright_white"),
            ]
            for item_name, slot_name in worn_results:
                parts.extend([
                    s.build_part("\n"),
                    s.build_part(" - ", "bright_white"),
                    s.build_part(item_name, "bright_cyan", True),
                    s.build_part(" on your ", "bright_white"),
                    s.build_part(slot_name, "bright_yellow", True),
                    s.build_part(".", "bright_white"),
                ])

            return s.display_command_result(session, parts)

        if selector == "all":
            wearable_items = []
            for inventory_item in list(session.inventory_items.values()):
                if s.is_item_equippable(inventory_item) and inventory_item.slot.strip().lower() == "armor":
                    wearable_items.append(inventory_item)

            wearable_items.sort(key=lambda item: (len(item.wear_slots) if item.wear_slots else 1, item.name.lower(), item.item_id))

            if not wearable_items:
                return s.display_error("You have nothing wearable in your inventory.", session)

            worn_results: list[tuple[str, str]] = []
            for item in wearable_items:
                worn, wear_result = s.wear_item(session, item)
                if worn:
                    worn_results.append((item.name, wear_result))

            if not worn_results:
                return s.display_error("You cannot wear any additional items right now.", session)

            parts = [
                s.build_part("You wear everything you can.", "bright_white"),
            ]
            for item_name, slot_name in worn_results:
                parts.extend([
                    s.build_part("\n"),
                    s.build_part(" - ", "bright_white"),
                    s.build_part(item_name, "bright_cyan", True),
                    s.build_part(" on your ", "bright_white"),
                    s.build_part(slot_name, "bright_yellow", True),
                    s.build_part(".", "bright_white"),
                ])

            return s.display_command_result(session, parts)

        item, resolve_error = s._resolve_wear_inventory_selector(session, selector)
        if resolve_error is not None or item is None:
            return s.display_error(resolve_error or "Unable to resolve inventory selector.", session)

        if item.slot.strip().lower() != "armor":
            return s.display_error(f"{item.name} cannot be worn.", session)

        worn, wear_result = s.wear_item(session, item, wear_location)
        if not worn:
            return s.display_error(wear_result, session)

        return s.display_command_result(session, [
            s.build_part("You wear ", "bright_white"),
            *s._build_item_reference_parts(item),
            s.build_part(" on your ", "bright_white"),
            s.build_part(wear_result, "bright_yellow", True),
            s.build_part(".", "bright_white"),
        ])

    if verb in {"drop", "dro", "dr"}:
        if not args:
            return s.display_error("Usage: drop <selector>", session)

        selector = ".".join(arg.strip().lower() for arg in args if arg.strip())
        if not selector:
            return s.display_error("Usage: drop <selector>", session)

        if selector.startswith("all.") and len(selector) > 4:
            item_selector = selector[4:]
            selector_tokens = {token for token in s.re.findall(r"[a-zA-Z0-9]+", item_selector) if token}
            if not selector_tokens:
                return s.display_error("Usage: drop all.<item>", session)

            inventory_matches = []
            for item in list(session.inventory_items.values()):
                item_keywords = {token for token in s.re.findall(r"[a-zA-Z0-9]+", item.name.lower()) if token}
                if selector_tokens.issubset(item_keywords):
                    inventory_matches.append(item)

            if not inventory_matches:
                return s.display_error(f"No inventory item matches '{item_selector}'.", session)

            dropped_items = []

            for item in inventory_matches:
                session.inventory_items.pop(item.item_id, None)
                s._add_item_to_room_ground(session, session.player.current_room_id, item)
                dropped_items.append(item)

            parts = [
                s.build_part("You drop all matching items.", "bright_white"),
            ]
            for item in dropped_items:
                parts.extend([
                    s.build_part("\n"),
                    s.build_part(" - ", "bright_white"),
                    s.build_part(item.name, s._item_highlight_color(item), True),
                ])
            return s.display_command_result(session, parts)

        coin_drop_match = s.re.match(r"^(\d+)\*coins?$", selector)
        if coin_drop_match is not None:
            drop_amount = int(coin_drop_match.group(1))
            if drop_amount <= 0:
                return s.display_error("Coin drop amount must be greater than zero.", session)
            if session.status.coins < drop_amount:
                return s.display_error(
                    f"You only have {session.status.coins} coins.",
                    session,
                )

            session.status.coins -= drop_amount
            room_id = session.player.current_room_id
            existing_pile = max(0, int(session.room_coin_piles.get(room_id, 0)))
            session.room_coin_piles[room_id] = existing_pile + drop_amount
            return s.display_command_result(session, [
                s.build_part("You drop ", "bright_white"),
                s.build_part(str(drop_amount), "bright_cyan", True),
                s.build_part(" coins into a pile on the ground.", "bright_white"),
            ])

        if selector == "all":
            inventory_items = list(session.inventory_items.values())

            if not inventory_items:
                return s.display_error("You have nothing to drop.", session)

            dropped_count = 0
            for item in inventory_items:
                session.inventory_items.pop(item.item_id, None)
                s._add_item_to_room_ground(session, session.player.current_room_id, item)
                dropped_count += 1

            return s.display_command_result(session, [
                s.build_part("You drop all carried items.", "bright_white"),
                s.build_part("\n"),
                s.build_part("Items dropped: ", "bright_white"),
                s.build_part(str(dropped_count), "bright_yellow", True),
            ])

        inventory_item, inventory_error = s._resolve_inventory_selector(session, selector)
        if inventory_item is not None:
            session.inventory_items.pop(inventory_item.item_id, None)
            s._add_item_to_room_ground(session, session.player.current_room_id, inventory_item)
            return s.display_command_result(session, [
                s.build_part("You drop ", "bright_white"),
                *s._build_item_reference_parts(inventory_item),
                s.build_part(".", "bright_white"),
            ])

        return s.display_error(inventory_error or "Unable to resolve inventory selector.", session)

    if verb in {"remove", "rem"}:
        if not args:
            return s.display_error("Usage: rem <selector>", session)

        selector = ".".join(arg.strip().lower() for arg in args if arg.strip())
        if selector.startswith("all.") and len(selector) > 4:
            item_selector = selector[4:]
            selector_tokens = {token for token in s.re.findall(r"[a-zA-Z0-9]+", item_selector) if token}
            if not selector_tokens:
                return s.display_error("Usage: rem all.<item>", session)

            worn_items = s.list_worn_items(session)
            matches = []
            seen_item_ids: set[str] = set()
            for _, worn_item in worn_items:
                if worn_item.item_id in seen_item_ids:
                    continue
                item_keywords = {token for token in s.re.findall(r"[a-zA-Z0-9]+", worn_item.name.lower()) if token}
                if selector_tokens.issubset(item_keywords):
                    matches.append(worn_item)
                seen_item_ids.add(worn_item.item_id)

            if not matches:
                return s.display_error(f"No equipped item matches '{item_selector}'.", session)

            removed_items = []
            for worn_item in matches:
                if s.unequip_item(session, worn_item):
                    removed_items.append(worn_item)

            if not removed_items:
                return s.display_error(f"No equipped item matches '{item_selector}'.", session)

            parts = [
                s.build_part("You remove all matching equipped items.", "bright_white"),
            ]
            for item in removed_items:
                parts.extend([
                    s.build_part("\n"),
                    s.build_part(" - ", "bright_white"),
                    s.build_part(item.name, s._item_highlight_color(item), True),
                ])
            return s.display_command_result(session, parts)

        if selector == "all":
            worn_items = s.list_worn_items(session)
            if not worn_items:
                return s.display_error("You have nothing to remove.", session)

            removed_items = []
            seen_item_ids: set[str] = set()
            for _, worn_item in worn_items:
                if worn_item.item_id in seen_item_ids:
                    continue
                if s.unequip_item(session, worn_item):
                    removed_items.append(worn_item)
                seen_item_ids.add(worn_item.item_id)

            if not removed_items:
                return s.display_error("You have nothing to remove.", session)

            parts = [
                s.build_part("You remove all equipped items and place them in your inventory.", "bright_white"),
            ]
            for item in removed_items:
                parts.extend([
                    s.build_part("\n"),
                    s.build_part(" - ", "bright_white"),
                    s.build_part(item.name, s._item_highlight_color(item), True),
                ])
            return s.display_command_result(session, parts)

        item, resolve_error = s.resolve_equipped_selector(session, selector)
        if resolve_error is not None or item is None:
            return s.display_error(resolve_error or "Unable to resolve equipped item selector.", session)

        was_equipped = s.unequip_item(session, item)
        if not was_equipped:
            return s.display_error(f"{item.name} is not currently worn or held.", session)

        return s.display_command_result(session, [
            s.build_part("You remove ", "bright_white"),
            s.build_part(item.name, s._item_highlight_color(item), True),
            s.build_part(" and place it in your inventory.", "bright_white"),
        ])

    return None


def handle_item_use_command(
    session: s.ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb != "use":
        return None

    selector = ".".join(arg.strip().lower() for arg in args if arg.strip())
    return s._use_misc_item(session, selector)
