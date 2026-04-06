import random

from attribute_config import get_player_class_by_id, load_attributes
from combat import end_combat, get_engaged_entity, maybe_auto_engage_current_room
from display import (
    build_line,
    build_menu_table_parts,
    build_part,
    display_command_result,
    display_error,
    display_prompt,
    display_room,
)
from experience import get_xp_to_next_level
from models import ClientSession
from player_resources import get_player_resource_caps
from settings import FLEE_SUCCESS_CHANCE
from sessions import enqueue_command, is_session_lagged
from world import get_room

OutboundMessage = dict[str, object]
OutboundResult = OutboundMessage | list[OutboundMessage]

PANEL_INNER_WIDTH = 34

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


def parse_command(command_text: str) -> tuple[str, list[str]]:
    normalized = command_text.strip()
    if not normalized:
        return "", []

    parts = normalized.split()
    verb = parts[0].lower()
    args = parts[1:]
    return verb, args


def _resolve_player_class_name(class_id: str) -> str:
    normalized_id = class_id.strip().lower()
    if not normalized_id:
        return "Wanderer"

    matched = get_player_class_by_id(normalized_id)
    if matched is None:
        return normalized_id.title()

    return str(matched.get("name", normalized_id.title())).strip() or normalized_id.title()


def _resource_color(current: int, maximum: int) -> str:
    if maximum <= 0:
        return "bright_white"

    ratio = max(0.0, min(1.0, float(current) / float(maximum)))
    if ratio <= 0.2:
        return "bright_red"
    if ratio <= 0.5:
        return "bright_yellow"
    return "bright_green"


def _format_effect_remaining_duration(effect) -> str:
    support_mode = str(getattr(effect, "support_mode", "timed")).strip().lower() or "timed"
    if support_mode == "battle_rounds":
        rounds = max(0, int(getattr(effect, "remaining_rounds", 0)))
        label = "round" if rounds == 1 else "rounds"
        return f"{rounds} {label}"

    if support_mode == "timed":
        hours = max(0, int(getattr(effect, "remaining_hours", 0)))
        label = "hour" if hours == 1 else "hours"
        return f"{hours} {label}"

    return "lingering"


def _build_cost_menu_parts(
    title: str,
    entries: list[tuple[str, str, int]],
    cost_resource_label: str,
    middle_column_header: str | None = None,
) -> list[dict]:
    if not entries:
        return [
            build_part(title, "bright_white", True),
            build_part("\n"),
            build_part("Nothing is known.", "bright_white"),
        ]

    has_middle_column = bool(middle_column_header and middle_column_header.strip())
    sorted_entries = sorted(
        [
            (
                str(name).strip() or title,
                str(middle_value).strip(),
                max(0, int(cost)),
            )
            for name, middle_value, cost in entries
        ],
        key=lambda entry: entry[0].lower(),
    )

    if has_middle_column:
        middle_header_label = str(middle_column_header or "").strip()
        rows = [
            [
                name,
                middle_value,
                "Free" if cost <= 0 else f"{cost} {cost_resource_label}",
            ]
            for name, middle_value, cost in sorted_entries
        ]
        return build_menu_table_parts(
            title,
            ["Name", middle_header_label, "Cost"],
            rows,
            column_colors=["bright_cyan", "bright_magenta", "bright_yellow"],
            column_alignments=["left", "left", "right"],
        )

    rows = [
        [
            name,
            "Free" if cost <= 0 else f"{cost} {cost_resource_label}",
        ]
        for name, _, cost in sorted_entries
    ]
    return build_menu_table_parts(
        title,
        ["Name", "Cost"],
        rows,
        column_colors=["bright_cyan", "bright_yellow"],
        column_alignments=["left", "right"],
    )


def display_score(session: ClientSession) -> OutboundMessage:
    caps = get_player_resource_caps(session)
    xp_total = max(0, int(session.player.experience_points))
    xp_to_next = get_xp_to_next_level(xp_total)
    class_name = _resolve_player_class_name(session.player.class_id)
    character_name = session.authenticated_character_name or "Unknown"
    room = get_room(session.player.current_room_id)
    room_name = room.title if room is not None else "Unknown"

    hp_now = max(0, int(session.status.hit_points))
    hp_cap = max(1, int(caps["hit_points"]))
    vigor_now = max(0, int(session.status.vigor))
    vigor_cap = max(1, int(caps["vigor"]))
    mana_now = max(0, int(session.status.mana))
    mana_cap = max(1, int(caps["mana"]))

    level_text = str(max(1, int(session.player.level)))
    coins_text = str(max(0, int(session.status.coins)))

    summary_line = f"Name: {character_name}   Class: {class_name}   Level: {level_text}"
    location_line = f"Location: {room_name}"
    resources_line = f"Health: {hp_now}/{hp_cap}   Vigor: {vigor_now}/{vigor_cap}   Mana: {mana_now}/{mana_cap}"
    coins_line = f"Coins: {coins_text}"
    xp_line = f"Experience: {xp_total}   To Next Level: {xp_to_next}"

    attribute_line_texts: list[str] = []
    configured_attributes = load_attributes()
    for attribute in configured_attributes:
        attribute_id = str(attribute.get("attribute_id", "")).strip().lower()
        if not attribute_id:
            continue
        attribute_name = str(attribute.get("name", attribute_id)).strip() or attribute_id
        value = int(session.player.attributes.get(attribute_id, 0))
        attribute_line_texts.append(f" - {attribute_name} ({attribute_id.upper()}): {value}")

    active_effects = sorted(
        list(session.active_support_effects),
        key=lambda effect: str(getattr(effect, "spell_name", "")).lower(),
    )
    effect_line_texts: list[str] = []
    if not active_effects:
        effect_line_texts.append(" - None")
    else:
        for effect in active_effects:
            effect_name = str(getattr(effect, "spell_name", "Effect")).strip() or "Effect"
            duration_text = _format_effect_remaining_duration(effect)
            effect_line_texts.append(f" - {effect_name} ({duration_text} remaining)")

    panel_width = max(
        PANEL_INNER_WIDTH,
        len("Adventurer's Ledger"),
        len(summary_line),
        len(location_line),
        len(resources_line),
        len(coins_line),
        len(xp_line),
        len("Attributes"),
        len("Active Effects"),
        max((len(text) for text in attribute_line_texts), default=0),
        max((len(text) for text in effect_line_texts), default=0),
    )
    divider = "-" * panel_width
    title_line = "Adventurer's Ledger".center(panel_width)

    parts: list[dict] = [
        build_part(title_line, "bright_cyan", True),
        build_part("\n"),
        build_part(divider, "bright_black"),
        build_part("\n"),
        build_part("Name: ", "bright_white"),
        build_part(character_name, "bright_yellow", True),
        build_part("   Class: ", "bright_white"),
        build_part(class_name, "bright_cyan", True),
        build_part("   Level: ", "bright_white"),
        build_part(level_text, "bright_green", True),
        build_part("\n"),
        build_part("Location: ", "bright_white"),
        build_part(room_name, "bright_magenta", True),
        build_part("\n"),
        build_part(divider, "bright_black"),
        build_part("\n"),
        build_part("Health: ", "bright_white"),
        build_part(f"{hp_now}/{hp_cap}", _resource_color(hp_now, hp_cap), True),
        build_part("   Vigor: ", "bright_white"),
        build_part(f"{vigor_now}/{vigor_cap}", _resource_color(vigor_now, vigor_cap), True),
        build_part("   Mana: ", "bright_white"),
        build_part(f"{mana_now}/{mana_cap}", _resource_color(mana_now, mana_cap), True),
        build_part("\n"),
        build_part("Coins: ", "bright_white"),
        build_part(str(max(0, int(session.status.coins))), "bright_cyan", True),
        build_part("\n"),
        build_part("Experience: ", "bright_white"),
        build_part(str(xp_total), "bright_cyan", True),
        build_part("   To Next Level: ", "bright_white"),
        build_part(str(xp_to_next), "bright_green", True),
        build_part("\n"),
        build_part(divider, "bright_black"),
        build_part("\n"),
        build_part("Attributes", "bright_white", True),
    ]

    for attribute in configured_attributes:
        attribute_id = str(attribute.get("attribute_id", "")).strip().lower()
        if not attribute_id:
            continue
        attribute_name = str(attribute.get("name", attribute_id)).strip() or attribute_id
        value = int(session.player.attributes.get(attribute_id, 0))
        parts.extend([
            build_part("\n"),
            build_part(" - ", "bright_white"),
            build_part(attribute_name, "bright_cyan", True),
            build_part(" (", "bright_white"),
            build_part(attribute_id.upper(), "bright_yellow", True),
            build_part("): ", "bright_white"),
            build_part(str(value), "bright_green", True),
        ])

    parts.extend([
        build_part("\n"),
        build_part(divider, "bright_black"),
        build_part("\n"),
        build_part("Active Effects", "bright_white", True),
    ])

    if not active_effects:
        parts.extend([
            build_part("\n"),
            build_part(" - None", "bright_black"),
        ])
    else:
        for effect in active_effects:
            effect_name = str(getattr(effect, "spell_name", "Effect")).strip() or "Effect"
            duration_text = _format_effect_remaining_duration(effect)
            parts.extend([
                build_part("\n"),
                build_part(" - ", "bright_white"),
                build_part(effect_name, "bright_magenta", True),
                build_part(" (", "bright_white"),
                build_part(duration_text, "bright_yellow", True),
                build_part(" remaining)", "bright_white"),
            ])

    return display_command_result(session, parts)


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

    exits = list(current_room.exits.items())
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

def initial_auth_prompt(session: ClientSession) -> OutboundMessage:
    from command_handlers.auth import initial_auth_prompt as _initial_auth_prompt

    return _initial_auth_prompt(session)


def login_prompt(session: ClientSession) -> OutboundMessage:
    from command_handlers.auth import login_prompt as _login_prompt

    return _login_prompt(session)


def execute_command(session: ClientSession, command_text: str) -> OutboundResult:
    from command_handlers.registry import dispatch_command

    return dispatch_command(session, command_text)


async def process_input_message(message: dict, session: ClientSession) -> OutboundResult:
    payload = message["payload"]
    input_text = payload.get("text")

    if input_text is None:
        return display_prompt(session)

    if not isinstance(input_text, str):
        return display_error("Field 'payload.text' must be a string.", session)

    input_text = input_text.strip()
    if not input_text:
        return display_prompt(session)

    if not session.is_authenticated:
        from command_handlers.auth import process_auth_input

        return process_auth_input(session, input_text)

    if is_session_lagged(session):
        was_queued, queue_message = enqueue_command(session, input_text)
        if not was_queued:
            return display_error(queue_message, session)

        return {"type": "noop"}

    return execute_command(session, input_text)


async def dispatch_message(message: dict, session: ClientSession) -> OutboundResult:
    msg_type = message["type"]

    if msg_type == "input":
        return await process_input_message(message, session)

    return display_error(f"Unsupported message type: {msg_type}")
