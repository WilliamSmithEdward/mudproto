from . import shared as s


HandledResult = s.OutboundResult | None


def handle_observation_command(
    session: s.ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb in {"look", "lo", "loo"}:
        room = s.get_room(session.player.current_room_id)
        if room is None:
            return s.display_error(f"Current room not found: {session.player.current_room_id}", session)

        if args:
            target_text = " ".join(args).strip()
            normalized_selector, search_room_item = s._normalize_item_look_selector(target_text)
            if not normalized_selector:
                return s.display_room(session, room)

            if search_room_item:
                room_item, room_item_error = s._resolve_room_ground_item_selector(
                    session,
                    session.player.current_room_id,
                    normalized_selector,
                )
                if room_item is not None:
                    return s._display_item_examination(session, room_item, default_location="Room")
                return s.display_error(room_item_error or f"No room item matches '{normalized_selector}'.", session)

            owned_item, owned_location, _ = s._resolve_owned_item_selector(session, normalized_selector)
            if owned_item is not None:
                return s._display_item_examination(session, owned_item, default_location=str(owned_location or "Inventory"))

            player_target, _ = s._resolve_room_player_selector(session, normalized_selector)
            if player_target is not None:
                return s.display_player_summary(session, player_target)

            entity_target, entity_error = s.resolve_room_entity_selector(
                session,
                session.player.current_room_id,
                normalized_selector,
                living_only=True,
            )
            if entity_target is not None:
                return s.display_entity_summary(session, entity_target)

            corpse_target, _ = s.resolve_room_corpse_selector(
                session,
                session.player.current_room_id,
                normalized_selector,
            )
            if corpse_target is not None:
                return s._display_corpse_examination(session, corpse_target)

            return s.display_error(entity_error or f"No target named '{normalized_selector}' is here.", session)

        return s.display_room(session, room)

    if verb in {"sc", "sca", "scan"}:
        room = s.get_room(session.player.current_room_id)
        if room is None:
            return s.display_error(f"Current room not found: {session.player.current_room_id}", session)

        return s.display_exits(session, room)

    if verb in {"ex", "exa", "exam", "exami", "examin", "examine"}:
        selector_text = " ".join(args).strip()
        if not selector_text:
            return s.display_error("Usage: examine <item|corpse selector> [in room]", session)

        normalized_selector, search_room_item = s._normalize_item_look_selector(selector_text)
        if not normalized_selector:
            return s.display_error("Usage: examine <item|corpse selector> [in room]", session)

        if search_room_item:
            room_item, room_item_error = s._resolve_room_ground_item_selector(
                session,
                session.player.current_room_id,
                normalized_selector,
            )
            if room_item is not None:
                return s._display_item_examination(session, room_item, default_location="Room")
            return s.display_error(room_item_error or f"No room item matches '{normalized_selector}'.", session)

        owned_item, owned_location, _ = s._resolve_owned_item_selector(session, normalized_selector)
        if owned_item is not None:
            return s._display_item_examination(session, owned_item, default_location=str(owned_location or "Inventory"))

        corpse, resolve_error = s.resolve_room_corpse_selector(
            session,
            session.player.current_room_id,
            normalized_selector,
        )
        if corpse is None:
            return s.display_error(resolve_error or f"No corpse matching '{normalized_selector}' is here.", session)

        return s._display_corpse_examination(session, corpse)

    return None
