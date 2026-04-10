from containers import display_container_examination, is_item_container
from display_feedback import display_error
from display_room import display_entity_summary, display_exits, display_player_summary, display_room
from item_logic import _display_item_examination
from models import ClientSession
from room_exits import normalize_direction_token
from room_objects import display_room_object_examination, resolve_room_object_selector
from targeting_entities import resolve_room_corpse_selector, resolve_room_entity_selector
from targeting_follow import _resolve_room_player_selector
from targeting_items import _resolve_owned_item_selector, _resolve_room_ground_item_selector
from targeting_parsing import _normalize_item_look_selector
import world as _world

from .types import OutboundResult

get_room = getattr(_world, "get_room")


HandledResult = OutboundResult | None


def _resolve_directional_room_look(room, selector_text: str):
    cleaned_selector = str(selector_text).strip().lower()
    if not cleaned_selector or " " in cleaned_selector:
        return None

    normalized_direction = normalize_direction_token(cleaned_selector)
    if normalized_direction not in room.exits:
        return None

    destination_room_id = room.exits.get(normalized_direction)
    if not destination_room_id:
        return None

    return get_room(destination_room_id)


def handle_observation_command(
    session: ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb in {"look", "lo", "loo"}:
        room = get_room(session.player.current_room_id)
        if room is None:
            return display_error(f"Current room not found: {session.player.current_room_id}", session)

        if args:
            target_text = " ".join(args).strip()
            normalized_selector, search_room_item = _normalize_item_look_selector(target_text)
            if not normalized_selector:
                return display_room(session, room)

            directional_room = _resolve_directional_room_look(room, normalized_selector)
            if directional_room is not None:
                return display_room(session, directional_room)

            if search_room_item:
                room_item, room_item_error = _resolve_room_ground_item_selector(
                    session,
                    session.player.current_room_id,
                    normalized_selector,
                )
                if room_item is not None:
                    if is_item_container(room_item):
                        return display_container_examination(session, room_item, default_location="Room")
                    return _display_item_examination(session, room_item, default_location="Room")

                room_object, room_object_error = resolve_room_object_selector(room, normalized_selector)
                if room_object is not None:
                    return display_room_object_examination(session, room, room_object)

                return display_error(
                    room_object_error or room_item_error or f"No room item or feature matches '{normalized_selector}'.",
                    session,
                )

            owned_item, owned_location, _ = _resolve_owned_item_selector(session, normalized_selector)
            if owned_item is not None:
                if is_item_container(owned_item):
                    return display_container_examination(session, owned_item, default_location=str(owned_location or "Inventory"))
                return _display_item_examination(session, owned_item, default_location=str(owned_location or "Inventory"))

            room_item, _ = _resolve_room_ground_item_selector(
                session,
                session.player.current_room_id,
                normalized_selector,
            )
            if room_item is not None:
                if is_item_container(room_item):
                    return display_container_examination(session, room_item, default_location="Room")
                return _display_item_examination(session, room_item, default_location="Room")

            room_object, _ = resolve_room_object_selector(room, normalized_selector)
            if room_object is not None:
                return display_room_object_examination(session, room, room_object)

            player_target, _ = _resolve_room_player_selector(session, normalized_selector)
            if player_target is not None:
                return display_player_summary(session, player_target)

            entity_target, entity_error = resolve_room_entity_selector(
                session,
                session.player.current_room_id,
                normalized_selector,
                living_only=True,
            )
            if entity_target is not None:
                return display_entity_summary(session, entity_target)

            corpse_target, _ = resolve_room_corpse_selector(
                session,
                session.player.current_room_id,
                normalized_selector,
            )
            if corpse_target is not None:
                return display_container_examination(session, corpse_target)

            return display_error(entity_error or f"No target named '{normalized_selector}' is here.", session)

        return display_room(session, room)

    if verb in {"sc", "sca", "scan"}:
        room = get_room(session.player.current_room_id)
        if room is None:
            return display_error(f"Current room not found: {session.player.current_room_id}", session)

        return display_exits(session, room)

    if verb in {"ex", "exa", "exam", "exami", "examin", "examine"}:
        selector_text = " ".join(args).strip()
        if not selector_text:
            return display_error("Usage: examine <item|corpse selector> [in room]", session)

        normalized_selector, search_room_item = _normalize_item_look_selector(selector_text)
        if not normalized_selector:
            return display_error("Usage: examine <item|corpse selector> [in room]", session)

        room = get_room(session.player.current_room_id)

        if search_room_item:
            room_item, room_item_error = _resolve_room_ground_item_selector(
                session,
                session.player.current_room_id,
                normalized_selector,
            )
            if room_item is not None:
                if is_item_container(room_item):
                    return display_container_examination(session, room_item, default_location="Room")
                return _display_item_examination(session, room_item, default_location="Room")

            if room is not None:
                room_object, room_object_error = resolve_room_object_selector(room, normalized_selector)
                if room_object is not None:
                    return display_room_object_examination(session, room, room_object)
            else:
                room_object_error = None

            return display_error(room_object_error or room_item_error or f"No room item or feature matches '{normalized_selector}'.", session)

        owned_item, owned_location, _ = _resolve_owned_item_selector(session, normalized_selector)
        if owned_item is not None:
            if is_item_container(owned_item):
                return display_container_examination(session, owned_item, default_location=str(owned_location or "Inventory"))
            return _display_item_examination(session, owned_item, default_location=str(owned_location or "Inventory"))

        room_item, _ = _resolve_room_ground_item_selector(
            session,
            session.player.current_room_id,
            normalized_selector,
        )
        if room_item is not None:
            if is_item_container(room_item):
                return display_container_examination(session, room_item, default_location="Room")
            return _display_item_examination(session, room_item, default_location="Room")

        if room is not None:
            room_object, _ = resolve_room_object_selector(room, normalized_selector)
            if room_object is not None:
                return display_room_object_examination(session, room, room_object)

        corpse, resolve_error = resolve_room_corpse_selector(
            session,
            session.player.current_room_id,
            normalized_selector,
        )
        if corpse is None:
            return display_error(resolve_error or f"No corpse matching '{normalized_selector}' is here.", session)

        return display_container_examination(session, corpse)

    return None
