from equipment import get_equipped_main_hand, get_equipped_off_hand, get_held_weapon, list_equipment
from models import ClientSession
from protocol import build_response
from sessions import is_session_lagged
from combat import get_engaged_entity, get_entity_condition, get_health_condition, list_room_entities
from world import Room, get_room


PLAYER_REFERENCE_MAX_HP = 575


def build_part(text: str, fg: str = "bright_white", bold: bool = False) -> dict:
    return {
        "text": text,
        "fg": fg,
        "bold": bold
    }


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
        build_part(f" {status.vigor}V {status.extra_lives}X {status.coins}C [Me:", "bright_white"),
        build_part(me_condition.title(), me_condition_color, True),
        build_part("]", "bright_white"),
    ]

    engaged_entity = get_engaged_entity(session)
    if engaged_entity is not None:
        npc_condition, npc_condition_color = get_entity_condition(engaged_entity)
        parts.extend([
            build_part(" [NPC:", "bright_white"),
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
    return build_response("display", {
        "parts": parts,
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
        build_part(". Condition: ", "bright_white"),
        build_part(me_condition, me_condition_color, True),
    ]

    if engaged_entity is not None:
        npc_condition, npc_condition_color = get_entity_condition(engaged_entity)
        parts.extend([
            build_part(". Engaged with ", "bright_white"),
            build_part(engaged_entity.name, "bright_red", True),
            build_part(" (", "bright_white"),
            build_part(npc_condition, npc_condition_color, True),
            build_part(").", "bright_white"),
        ])

    return build_display(parts, prompt_after=prompt_after, prompt_parts=prompt_parts)


def display_equipment(session: ClientSession) -> dict:
    prompt_after, prompt_parts = resolve_prompt(session, True)
    main_hand = get_equipped_main_hand(session)
    off_hand = get_equipped_off_hand(session)
    held_weapon = get_held_weapon(session)

    parts = [
        build_part("Equipment", "bright_white", True),
        build_part("\n"),
        build_part("Main hand: ", "bright_white"),
    ]

    if main_hand is None:
        parts.append(build_part("None", "bright_yellow", True))
    else:
        parts.extend([
            build_part(main_hand.name, "bright_cyan", True),
            build_part(" [", "bright_white"),
            build_part(main_hand.template_id, "bright_magenta"),
            build_part("]", "bright_white"),
        ])

    parts.extend([
        build_part("\n"),
        build_part("Off hand: ", "bright_white"),
    ])

    if off_hand is None:
        parts.append(build_part("None", "bright_yellow", True))
    else:
        parts.extend([
            build_part(off_hand.name, "bright_cyan", True),
            build_part(" [", "bright_white"),
            build_part(off_hand.template_id, "bright_magenta"),
            build_part("]", "bright_white"),
        ])

    if held_weapon is not None:
        parts.extend([
            build_part("\n"),
            build_part("Held weapon profile: ", "bright_white"),
            build_part(f"{held_weapon.damage_dice_count}d{held_weapon.damage_dice_sides}", "bright_yellow", True),
            build_part(" +", "bright_white"),
            build_part(str(held_weapon.damage_roll_modifier), "bright_yellow", True),
            build_part(" damage mod | +", "bright_white"),
            build_part(str(held_weapon.hit_roll_modifier), "bright_yellow", True),
            build_part(" hit mod", "bright_white"),
            build_part(" | type: ", "bright_white"),
            build_part(held_weapon.weapon_type, "bright_cyan", True),
        ])
    else:
        parts.extend([
            build_part("\n"),
            build_part("Held weapon profile: unarmed", "bright_white"),
        ])

    equipment_items = list_equipment(session)
    if equipment_items:
        parts.extend([
            build_part("\n"),
            build_part("\n"),
            build_part("Owned equipment:", "bright_white", True),
        ])

        for item in equipment_items:
            slot_label = item.slot.capitalize()
            hand_label = None
            if main_hand is not None and item.item_id == main_hand.item_id:
                hand_label = "main hand"
            elif off_hand is not None and item.item_id == off_hand.item_id:
                hand_label = "off hand"

            parts.extend([
                build_part("\n"),
                build_part(" - ", "bright_white"),
                build_part(item.name, "bright_magenta", True),
                build_part(f" ({slot_label}", "bright_white"),
            ])
            if hand_label is not None:
                parts.extend([
                    build_part(f", {hand_label}", "bright_cyan", True),
                ])
            parts.extend([
                build_part(")", "bright_white"),
                build_part(" [", "bright_white"),
                build_part(item.item_id, "bright_yellow"),
                build_part("]", "bright_white"),
                build_part(" | keys: ", "bright_white"),
                build_part(".".join(item.keywords) if item.keywords else "none", "bright_cyan"),
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
                build_part(entity.name, "bright_magenta", True),
                build_part(" (", "bright_white"),
                build_part(condition_text, condition_color, True),
                build_part(" condition)", "bright_white"),
            ])

    return build_display(parts, prompt_after=prompt_after, prompt_parts=prompt_parts)
