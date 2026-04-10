import random

from combat_state import end_combat, get_engaged_entity, maybe_auto_engage_current_room
from display_core import build_line, build_part
from display_feedback import display_command_result, display_error
from display_room import display_room
from models import ClientSession
from room_exits import can_traverse_exit
from settings import FLEE_SUCCESS_CHANCE
import world as _world

from .types import OutboundMessage, OutboundResult


get_room = getattr(_world, "get_room")
HandledResult = OutboundResult | None
DIRECTION_ALIASES = {
    "n": "north",
    "no": "north",
    "nor": "north",
    "nort": "north",
    "s": "south",
    "so": "south",
    "sou": "south",
    "sout": "south",
    "e": "east",
    "ea": "east",
    "eas": "east",
    "w": "west",
    "we": "west",
    "wes": "west",
    "u": "up",
    "d": "down",
    "do": "down",
    "dow": "down",
}


def normalize_direction(direction: str) -> str:
    direction = direction.lower().strip()
    return DIRECTION_ALIASES.get(direction, direction)


def build_auto_aggro_outbound(session: ClientSession, room_display: OutboundMessage) -> OutboundResult:
    maybe_auto_engage_current_room(session)
    return room_display


def _attach_movement_metadata(
    outbound: OutboundResult,
    *,
    from_room_id: str,
    to_room_id: str,
    direction: str,
    action: str,
    allow_followers: bool,
) -> OutboundResult:
    payload = outbound.get("payload") if isinstance(outbound, dict) else None
    if isinstance(payload, dict):
        payload["movement"] = {
            "from_room_id": str(from_room_id).strip(),
            "to_room_id": str(to_room_id).strip(),
            "direction": str(direction).strip().lower(),
            "action": str(action).strip().lower() or "leaves",
            "allow_followers": bool(allow_followers),
        }
    return outbound


def flee(session: ClientSession) -> OutboundResult:
    entity = get_engaged_entity(session)
    if entity is None:
        return display_error("You are not engaged with anything.", session)

    current_room = get_room(session.player.current_room_id)
    if current_room is None:
        return display_error(f"Current room not found: {session.player.current_room_id}", session)

    exits = [
        (direction, room_id)
        for direction, room_id in current_room.exits.items()
        if can_traverse_exit(current_room, direction)[0]
    ]
    if not exits:
        return display_error("There is nowhere to flee.", session)

    if random.random() >= FLEE_SUCCESS_CHANCE:
        return display_command_result(session, [
            build_part("You try to flee from ", "bright_white"),
            build_part(entity.name),
            build_part(", but fail.", "bright_white"),
        ])

    flee_direction, next_room_id = random.choice(exits)
    next_room = get_room(next_room_id)
    if next_room is None:
        return display_error(f"Destination room not found: {next_room_id}", session)

    session.player.current_room_id = next_room.room_id
    end_combat(session)

    room_display = display_room(session, next_room)
    payload = room_display.get("payload") if isinstance(room_display, dict) else None
    if isinstance(payload, dict):
        lines = payload.get("lines")
        if isinstance(lines, list):
            payload["lines"] = [
                build_line(
                    build_part("You flee ", "bright_white"),
                    build_part(flee_direction, "bright_yellow", True),
                    build_part(".", "bright_white"),
                ),
            ] + lines

    return _attach_movement_metadata(
        build_auto_aggro_outbound(session, room_display),
        from_room_id=current_room.room_id,
        to_room_id=next_room.room_id,
        direction=normalize_direction(flee_direction),
        action="flees",
        allow_followers=False,
    )


def try_move(session: ClientSession, direction: str) -> OutboundResult:
    if session.combat.engaged_entity_ids:
        return display_error("You cannot move while engaged in combat. Try flee.", session)

    current_room = get_room(session.player.current_room_id)
    if current_room is None:
        return display_error(f"Current room not found: {session.player.current_room_id}", session)

    normalized_direction = normalize_direction(direction)
    next_room_id = current_room.exits.get(normalized_direction)
    if next_room_id is None:
        return display_error(f"You cannot go {normalized_direction} from here.", session)

    can_traverse, blocked_message = can_traverse_exit(current_room, normalized_direction)
    if not can_traverse:
        return display_error(blocked_message or f"You cannot go {normalized_direction} from here.", session)

    next_room = get_room(next_room_id)
    if next_room is None:
        return display_error(f"Destination room not found: {next_room_id}", session)

    session.player.current_room_id = next_room.room_id
    end_combat(session)

    room_display = display_room(session, next_room)
    return _attach_movement_metadata(
        build_auto_aggro_outbound(session, room_display),
        from_room_id=current_room.room_id,
        to_room_id=next_room.room_id,
        direction=normalized_direction,
        action="leaves",
        allow_followers=True,
    )


def handle_movement_command(
    session: ClientSession,
    verb: str,
    _args: list[str],
    _command_text: str,
) -> HandledResult:
    if normalize_direction(verb) in {"north", "south", "east", "west", "up", "down"}:
        return try_move(session, verb)

    return None
