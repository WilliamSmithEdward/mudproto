import asyncio

from equipment import list_inventory_items, list_worn_items
from models import ClientSession
from protocol import build_response
from sessions import is_session_lagged
from combat import get_engaged_entity, get_entity_condition, get_health_condition, list_room_corpses, list_room_entities
from world import Room, get_room


PLAYER_REFERENCE_MAX_HP = 575


def _capitalize_after_newlines(text: str) -> str:
    """Capitalize the first letter after each newline in text."""
    if not text:
        return text
    
    result = []
    capitalize_next = False
    for i, char in enumerate(text):
        if i == 0:
            # Capitalize the very first character
            result.append(char.upper() if char.isalpha() else char)
        elif char == "\n":
            result.append(char)
            capitalize_next = True
        elif capitalize_next and char.isalpha():
            result.append(char.upper())
            capitalize_next = False
        else:
            result.append(char)
            capitalize_next = False
    
    return "".join(result)


def build_part(text: str, fg: str = "bright_white", bold: bool = False) -> dict:
    return {
        "text": text,
        "fg": fg,
        "bold": bold
    }


def _get_tick_seconds_remaining(session: ClientSession) -> int | None:
    if session.next_game_tick_monotonic is None:
        return None

    try:
        now = asyncio.get_running_loop().time()
    except RuntimeError:
        return None

    return max(0, int(session.next_game_tick_monotonic - now))


def build_prompt_parts(session: ClientSession) -> list[dict]:
    room = get_room(session.player.current_room_id)
    exit_letters = ""

    if room is not None and room.exits:
        direction_letters = {
            "north": "N",
            "south": "S",
            "east": "E",
            "west": "W",
            "up": "U",
            "down": "D",
        }
        exit_letters = "".join(
            direction_letters[direction]
            for direction in room.exits.keys()
            if direction in direction_letters
        )

    if not exit_letters:
        exit_letters = "None"

    status = session.status
    me_condition, me_condition_color = get_health_condition(status.hit_points, PLAYER_REFERENCE_MAX_HP)

    parts = [
        build_part(f"{status.hit_points}H", me_condition_color, True),
        build_part(f" {status.vigor}V {status.mana}M {status.coins}C", "bright_white"),
    ]

    tick_seconds_remaining = _get_tick_seconds_remaining(session)
    if tick_seconds_remaining is not None:
        parts.extend([
            build_part(" [Tick:", "bright_white"),
            build_part(f"{tick_seconds_remaining}s", "bright_yellow", True),
            build_part("]", "bright_white"),
        ])

    parts.extend([
        build_part(" [Me:", "bright_white"),
        build_part(me_condition.title(), me_condition_color, True),
        build_part("]", "bright_white"),
    ])

    engaged_entity = get_engaged_entity(session)
    if engaged_entity is not None:
        npc_condition, npc_condition_color = get_entity_condition(engaged_entity)
        parts.extend([
            build_part(" [", "bright_white"),
            build_part(engaged_entity.name),
            build_part(":", "bright_white"),
            build_part(npc_condition.title(), npc_condition_color, True),
            build_part("]", "bright_white"),
        ])

    parts.append(build_part(f" Exits:{exit_letters}> ", "bright_white"))
    return parts


def build_display(
    parts: list[dict],
    *,
    blank_lines_before: int = 1,
    prompt_after: bool = False,
    prompt_parts: list[dict] | None = None,
    starts_on_new_line: bool = False
) -> dict:
    # Capitalize first letter after newlines in the full text
    full_text = "".join(p.get("text", "") for p in parts)
    capitalized_text = _capitalize_after_newlines(full_text)
    
    # Rebuild parts with capitalized text, maintaining original formatting
    offset = 0
    new_parts = []
    for part in parts:
        original_text = part.get("text", "")
        text_len = len(original_text)
        if text_len > 0:
            capitalized_portion = capitalized_text[offset:offset + text_len]
            offset += text_len
            new_parts.append({
                "text": capitalized_portion,
                "fg": part.get("fg", "bright_white"),
                "bold": part.get("bold", False)
            })
        else:
            new_parts.append(part)
    
    return build_response("display", {
        "parts": new_parts,
        "blank_lines_before": blank_lines_before,
        "prompt_after": prompt_after,
        "prompt_parts": prompt_parts,
        "starts_on_new_line": starts_on_new_line
    })


def display_text(
    text: str,
    *,
    fg: str = "bright_white",
    bold: bool = False,
    blank_lines_before: int = 1,
    prompt_after: bool = False,
    prompt_parts: list[dict] | None = None
) -> dict:
    return build_display(
        [build_part(text, fg, bold)],
        blank_lines_before=blank_lines_before,
        prompt_after=prompt_after,
        prompt_parts=prompt_parts
    )


def should_show_prompt(session: ClientSession) -> bool:
    return not is_session_lagged(session)


def mark_prompt_pending(session: ClientSession) -> None:
    session.prompt_pending_after_lag = True


def resolve_prompt(session: ClientSession, prompt_after: bool) -> tuple[bool, list[dict] | None]:
    if not prompt_after:
        return False, None

    if should_show_prompt(session):
        session.prompt_pending_after_lag = False
        return True, build_prompt_parts(session)

    mark_prompt_pending(session)
    return False, None


def display_prompt(session: ClientSession) -> dict:
    prompt_after, prompt_parts = resolve_prompt(session, True)
    return build_display([], prompt_after=prompt_after, prompt_parts=prompt_parts)


def display_force_prompt(session: ClientSession) -> dict:
    return build_display([], prompt_after=True, prompt_parts=build_prompt_parts(session))


def display_connected(session: ClientSession) -> dict:
    return build_display([
        build_part("Connection established.", "bright_green", True)
    ])


def display_hello(name: str, session: ClientSession) -> dict:
    prompt_after, prompt_parts = resolve_prompt(session, True)
    return build_display([
        build_part("Hello, ", "bright_green"),
        build_part(str(name), "bright_white", True)
    ], prompt_after=prompt_after, prompt_parts=prompt_parts)


def display_pong(session: ClientSession) -> dict:
    prompt_after, prompt_parts = resolve_prompt(session, True)
    return display_text(
        "Ping received.",
        fg="bright_cyan",
        prompt_after=prompt_after,
        prompt_parts=prompt_parts
    )


def display_whoami(session: ClientSession) -> dict:
    prompt_after, prompt_parts = resolve_prompt(session, True)
    me_condition, me_condition_color = get_health_condition(session.status.hit_points, PLAYER_REFERENCE_MAX_HP)
    engaged_entity = get_engaged_entity(session)

    parts = [
        build_part("You are in ", "bright_white"),
        build_part(session.player.current_room_id, "bright_green", True),
        build_part(". Class: ", "bright_white"),
        build_part(session.player.class_id or "unassigned", "bright_cyan", True),
        build_part(". Condition: ", "bright_white"),
        build_part(me_condition, me_condition_color, True),
    ]

    if engaged_entity is not None:
        npc_condition, npc_condition_color = get_entity_condition(engaged_entity)
        parts.extend([
            build_part(". Engaged with ", "bright_white"),
            build_part(engaged_entity.name, bold=True),
            build_part(" (", "bright_white"),
            build_part(npc_condition, npc_condition_color, True),
            build_part(").", "bright_white"),
        ])

    return build_display(parts, prompt_after=prompt_after, prompt_parts=prompt_parts)


def display_equipment(session: ClientSession) -> dict:
    prompt_after, prompt_parts = resolve_prompt(session, True)
    worn_items = list_worn_items(session)

    parts = [
        build_part("Worn Equipment", "bright_white", True),
    ]

    if not worn_items:
        parts.extend([
            build_part("\n"),
            build_part(" - nothing", "bright_yellow", True),
        ])
    else:
        for wear_slot, item in worn_items:
            parts.extend([
                build_part("\n"),
                build_part(" - ", "bright_white"),
                build_part(wear_slot, "bright_cyan", True),
                build_part(": ", "bright_white"),
                build_part(item.name, "bright_magenta", True),
            ])

    return build_display(parts, prompt_after=prompt_after, prompt_parts=prompt_parts)


def display_inventory(session: ClientSession) -> dict:
    prompt_after, prompt_parts = resolve_prompt(session, True)
    equipment_items = list_inventory_items(session)
    misc_items = list(session.inventory_items.values())
    misc_items.sort(key=lambda item: item.name.lower())

    def _stack_counts(names: list[str]) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        display_names: dict[str, str] = {}
        order: list[str] = []

        for name in names:
            normalized = name.strip().lower()
            if not normalized:
                continue
            if normalized not in counts:
                counts[normalized] = 0
                display_names[normalized] = name
                order.append(normalized)
            counts[normalized] += 1

        return [(display_names[key], counts[key]) for key in order]

    parts = [
        build_part("Inventory", "bright_white", True),
    ]

    if not equipment_items and not misc_items:
        parts.extend([
            build_part("\n"),
            build_part(" - empty", "bright_yellow", True),
        ])
    else:
        equipment_stacks = _stack_counts([item.name for item in equipment_items])
        for item_name, count in equipment_stacks:
            parts.extend([
                build_part("\n"),
                build_part(" - ", "bright_white"),
                build_part(item_name, "bright_magenta", True),
            ])
            if count > 1:
                parts.extend([
                    build_part(" ", "bright_white"),
                    build_part(f"[{count}]", "bright_cyan", True),
                ])

    misc_stacks = _stack_counts([item.name for item in misc_items])
    for item_name, count in misc_stacks:
        parts.extend([
            build_part("\n"),
            build_part(" - ", "bright_white"),
            build_part(item_name, "bright_yellow", True),
        ])
        if count > 1:
            parts.extend([
                build_part(" ", "bright_white"),
                build_part(f"[{count}]", "bright_cyan", True),
            ])

    return build_display(parts, prompt_after=prompt_after, prompt_parts=prompt_parts)


def display_error(message: str, session: ClientSession | None = None) -> dict:
    prompt_after = False
    prompt_parts: list[dict] | None = None

    if session is not None:
        prompt_after, prompt_parts = resolve_prompt(session, True)

    return build_display(
        [build_part(f"Error: {message}", "bright_red", True)],
        prompt_after=prompt_after,
        prompt_parts=prompt_parts,
    )


def display_system(message: str) -> dict:
    return display_text(message, fg="bright_cyan")


def display_queue_ack(session: ClientSession, command_text: str) -> dict:
    mark_prompt_pending(session)
    return build_display([
        build_part("Queued: ", "bright_yellow", True),
        build_part(f'"{command_text}"', "bright_white")
    ])


def display_command_result(
    session: ClientSession,
    parts: list[dict],
    *,
    blank_lines_before: int = 1,
    prompt_after: bool = True
) -> dict:
    prompt_after, prompt_parts = resolve_prompt(session, prompt_after)
    return build_display(
        parts,
        blank_lines_before=blank_lines_before,
        prompt_after=prompt_after,
        prompt_parts=prompt_parts
    )


def display_combat_round_result(session: ClientSession, parts: list[dict]) -> dict:
    return build_display(
        parts,
        prompt_after=False,
        starts_on_new_line=True
    )


def display_room(session: ClientSession, room: Room) -> dict:
    prompt_after, prompt_parts = resolve_prompt(session, True)

    parts = [
        build_part(room.title, "bright_green", True),
        build_part("\n"),
        build_part(room.description, "bright_white"),
    ]

    entities = list_room_entities(session, room.room_id)
    if entities:
        parts.extend([
            build_part("\n"),
            build_part("\n"),
            build_part("You see here:", "bright_white", True),
        ])

        for entity in entities:
            condition_text, condition_color = get_entity_condition(entity)
            parts.extend([
                build_part("\n"),
                build_part(" - ", "bright_white"),
                build_part(entity.name, bold=True),
                build_part(" (", "bright_white"),
                build_part(condition_text, condition_color, True),
                build_part(" condition)", "bright_white"),
            ])

    corpses = list_room_corpses(session, room.room_id)
    if corpses:
        parts.extend([
            build_part("\n"),
            build_part("\n"),
            build_part("Corpses:", "bright_white", True),
        ])

        for corpse in corpses:
            parts.extend([
                build_part("\n"),
                build_part(" - ", "bright_white"),
                build_part(f"{corpse.source_name} corpse", bold=True),
            ])

    room_coin_amount = max(0, int(session.room_coin_piles.get(room.room_id, 0)))
    if room_coin_amount > 0:
        parts.extend([
            build_part("\n"),
            build_part("\n"),
            build_part("Coin pile:", "bright_white", True),
            build_part("\n"),
            build_part(" - ", "bright_white"),
            build_part(str(room_coin_amount), "bright_cyan", True),
            build_part(" coins", "bright_white"),
        ])

    room_items = list(session.room_ground_items.get(room.room_id, {}).values())
    room_items.sort(key=lambda item: item.name.lower())

    room_item_counts: dict[str, int] = {}
    room_item_names: dict[str, str] = {}
    room_item_order: list[str] = []
    for item in room_items:
        normalized = item.name.strip().lower()
        if not normalized:
            continue
        if normalized not in room_item_counts:
            room_item_counts[normalized] = 0
            room_item_names[normalized] = item.name
            room_item_order.append(normalized)
        room_item_counts[normalized] += 1

    if room_items:
        parts.extend([
            build_part("\n"),
            build_part("\n"),
            build_part("Items on ground:", "bright_white", True),
        ])
        for item_key in room_item_order:
            parts.extend([
                build_part("\n"),
                build_part(" - ", "bright_white"),
                build_part(room_item_names[item_key], "bright_yellow", True),
            ])
            count = room_item_counts[item_key]
            if count > 1:
                parts.extend([
                    build_part(" ", "bright_white"),
                    build_part(f"[{count}]", "bright_cyan", True),
                ])

    return build_display(parts, prompt_after=prompt_after, prompt_parts=prompt_parts)
