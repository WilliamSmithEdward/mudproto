import asyncio

from assets import get_gear_template_by_id
from equipment import list_worn_items
from inventory import is_item_equippable
from grammar import capitalize_after_newlines
from experience import get_xp_to_next_level
from player_resources import get_player_resource_caps
from models import ClientSession
from protocol import build_response
from sessions import is_session_lagged, list_authenticated_room_players
from combat import get_engaged_entity, get_entity_condition, get_health_condition, list_room_corpses, list_room_entities
from world import Room, get_room


PANEL_INNER_WIDTH = 34


def build_part(text: str, fg: str = "bright_white", bold: bool = False) -> dict:
    return {
        "text": text,
        "fg": fg,
        "bold": bold
    }


def build_line(*parts: dict) -> list[dict]:
    return [part for part in parts if isinstance(part, dict)]


def _panel_divider() -> str:
    return "-" * PANEL_INNER_WIDTH


def _panel_title_line(title: str) -> str:
    return str(title).strip().center(PANEL_INNER_WIDTH)


def build_menu_table_parts(
    title: str,
    headers: list[str],
    rows: list[list[str]],
    *,
    column_colors: list[str] | None = None,
    row_cell_colors: list[list[str]] | None = None,
    column_alignments: list[str] | None = None,
    empty_message: str = "Nothing is known.",
) -> list[dict]:
    normalized_headers = [str(header).strip() for header in headers if str(header).strip()]
    if not normalized_headers:
        normalized_headers = ["Value"]

    column_count = len(normalized_headers)
    normalized_rows: list[list[str]] = []
    for row in rows:
        normalized_row = [str(cell) for cell in row[:column_count]]
        if len(normalized_row) < column_count:
            normalized_row.extend([""] * (column_count - len(normalized_row)))
        normalized_rows.append(normalized_row)

    if column_colors is None or len(column_colors) < column_count:
        base_colors = list(column_colors or [])
        base_colors.extend(["bright_cyan"] * (column_count - len(base_colors)))
        column_colors = base_colors

    if column_alignments is None or len(column_alignments) < column_count:
        base_alignments = list(column_alignments or [])
        base_alignments.extend(["left"] * (column_count - len(base_alignments)))
        column_alignments = base_alignments

    if not normalized_rows:
        return [
            build_part(_panel_title_line(title), "bright_cyan", True),
            build_part("\n"),
            build_part(_panel_divider(), "bright_black"),
            build_part("\n"),
            build_part(empty_message, "bright_white"),
        ]

    gap = 3
    col_widths: list[int] = []
    for col_index in range(column_count):
        max_cell = max(len(row[col_index]) for row in normalized_rows)
        col_widths.append(max(len(normalized_headers[col_index]), max_cell))

    content_width = sum(col_widths) + gap * (column_count - 1)
    panel_width = max(len(str(title).strip()), content_width)
    col_widths[0] += panel_width - content_width

    def _align_text(value: str, width: int, alignment: str) -> str:
        if alignment == "right":
            return value.rjust(width)
        if alignment == "center":
            return value.center(width)
        return value.ljust(width)

    parts: list[dict] = [
        build_part(str(title).strip().center(panel_width), "bright_cyan", True),
        build_part("\n"),
        build_part("-" * panel_width, "bright_black"),
        build_part("\n"),
    ]

    for col_index in range(column_count):
        header_text = _align_text(normalized_headers[col_index], col_widths[col_index], column_alignments[col_index])
        parts.append(build_part(header_text, "bright_white", True))
        if col_index < column_count - 1:
            parts.append(build_part(" " * gap, "bright_white"))

    parts.extend([
        build_part("\n"),
        build_part("-" * panel_width, "bright_black"),
    ])

    for row_index, row in enumerate(normalized_rows):
        parts.append(build_part("\n"))
        for col_index in range(column_count):
            cell_color = column_colors[col_index]
            if row_cell_colors is not None and row_index < len(row_cell_colors):
                color_row = row_cell_colors[row_index]
                if col_index < len(color_row) and str(color_row[col_index]).strip():
                    cell_color = str(color_row[col_index]).strip()

            aligned_cell = _align_text(row[col_index], col_widths[col_index], column_alignments[col_index])
            parts.append(build_part(aligned_cell, cell_color, True))
            if col_index < column_count - 1:
                parts.append(build_part(" " * gap, "bright_white"))

    return parts


def _normalize_part(part: dict) -> dict:
    return {
        "text": str(part.get("text", "")),
        "fg": part.get("fg", "bright_white"),
        "bold": part.get("bold", False),
    }


def _capitalize_parts(parts: list[dict]) -> list[dict]:
    full_text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
    capitalized_text = capitalize_after_newlines(full_text)

    offset = 0
    capitalized_parts: list[dict] = []
    for part in parts:
        if not isinstance(part, dict):
            continue

        normalized_part = _normalize_part(part)
        original_text = normalized_part["text"]
        text_len = len(original_text)
        capitalized_portion = capitalized_text[offset:offset + text_len]
        offset += text_len
        normalized_part["text"] = capitalized_portion
        capitalized_parts.append(normalized_part)

    return capitalized_parts


def parts_to_lines(parts: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = []
    current_line: list[dict] = []
    saw_part = False

    for part in parts:
        if not isinstance(part, dict):
            continue

        normalized_part = _normalize_part(part)
        text = normalized_part["text"]
        segments = text.split("\n")
        saw_part = True

        for index, segment in enumerate(segments):
            if segment:
                current_line.append({
                    "text": segment,
                    "fg": normalized_part["fg"],
                    "bold": normalized_part["bold"],
                })

            if index < len(segments) - 1:
                lines.append(current_line)
                current_line = []

    if current_line or (saw_part and not lines):
        lines.append(current_line)

    return lines


def _sanitize_lines(lines: list[list[dict]]) -> list[list[dict]]:
    sanitized_lines: list[list[dict]] = []
    for line in lines:
        if not isinstance(line, list):
            continue
        sanitized_line = [
            _normalize_part(part)
            for part in line
            if isinstance(part, dict)
        ]
        sanitized_lines.append(sanitized_line)
    return sanitized_lines


def _trim_empty_edge_lines(lines: list[list[dict]]) -> tuple[int, list[list[dict]], int]:
    trimmed_lines = list(lines)
    blank_lines_before = 0
    blank_lines_after = 0

    while trimmed_lines and not trimmed_lines[0]:
        blank_lines_before += 1
        trimmed_lines.pop(0)

    while trimmed_lines and not trimmed_lines[-1]:
        blank_lines_after += 1
        trimmed_lines.pop()

    return blank_lines_before, trimmed_lines, blank_lines_after


def _blank_lines(count: int) -> list[list[dict]]:
    return [[] for _ in range(max(0, count))]


def _get_tick_seconds_remaining(session: ClientSession) -> int | None:
    if session.next_game_tick_monotonic is None:
        return None

    try:
        now = asyncio.get_running_loop().time()
    except RuntimeError:
        return None

    return max(0, int(session.next_game_tick_monotonic - now))


def _direction_short_label(direction: str) -> str:
    direction_letters = {
        "north": "N",
        "south": "S",
        "east": "E",
        "west": "W",
        "up": "U",
        "down": "D",
    }
    normalized = str(direction).strip().lower()
    return direction_letters.get(normalized, normalized[:1].upper() or "?")


def _direction_sort_key(direction: str) -> tuple[int, str]:
    order = {
        "north": 0,
        "east": 1,
        "south": 2,
        "west": 3,
        "up": 4,
        "down": 5,
    }
    normalized = str(direction).strip().lower()
    return order.get(normalized, 99), normalized


def build_prompt_parts(session: ClientSession) -> list[dict]:
    if not session.is_authenticated:
        return [build_part("> ", "bright_white")]

    room = get_room(session.player.current_room_id)
    exit_letters = ""

    if room is not None and room.exits:
        exit_letters = "".join(
            _direction_short_label(direction)
            for direction in room.exits.keys()
            if str(direction).strip()
        )

    if not exit_letters:
        exit_letters = "None"

    status = session.status
    caps = get_player_resource_caps(session)
    me_condition, me_condition_color = get_health_condition(status.hit_points, caps["hit_points"])

    parts = [
        build_part(f"{status.hit_points}H", me_condition_color, True),
        build_part(f" {status.vigor}V {status.mana}M {status.coins}C", "bright_white"),
    ]

    xp_to_next_level = get_xp_to_next_level(session.player.experience_points)
    parts.extend([
        build_part(f" {xp_to_next_level}X", "bright_white"),
    ])

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
    blank_lines_after: int = 0,
    prompt_after: bool = False,
    prompt_parts: list[dict] | None = None,
    starts_on_new_line: bool = False
) -> dict:
    content_lines = parts_to_lines(_capitalize_parts(parts))
    extra_blank_lines_before, content_lines, extra_blank_lines_after = _trim_empty_edge_lines(content_lines)

    effective_blank_lines_before = blank_lines_before + extra_blank_lines_before
    effective_blank_lines_after = blank_lines_after + extra_blank_lines_after

    sanitized_content_lines = _sanitize_lines(content_lines)

    prompt_lines: list[list[dict]] = []
    if prompt_after and prompt_parts:
        prompt_lines = _sanitize_lines(parts_to_lines(_capitalize_parts(prompt_parts)))

    display_lines = _blank_lines(effective_blank_lines_before) + sanitized_content_lines

    if prompt_lines:
        # Keep prompt spacing deterministic: one blank line before prompt when content exists.
        prompt_prefix_blank_lines = 2 if sanitized_content_lines else effective_blank_lines_after
        prompt_lines = _blank_lines(prompt_prefix_blank_lines) + prompt_lines
    else:
        display_lines.extend(_blank_lines(effective_blank_lines_after))

    if starts_on_new_line:
        display_lines = [[]] + display_lines

    return build_response("display", {
        "lines": display_lines,
        "prompt_lines": prompt_lines,
    })


def build_display_lines(
    lines: list[list[dict]],
    *,
    blank_lines_before: int = 1,
    blank_lines_after: int = 0,
    prompt_after: bool = False,
    prompt_parts: list[dict] | None = None,
    starts_on_new_line: bool = False
) -> dict:
    flattened_parts: list[dict] = []
    for index, line in enumerate(lines):
        if index > 0:
            flattened_parts.append(build_part("\n"))
        for part in line:
            if isinstance(part, dict):
                flattened_parts.append(_normalize_part(part))

    return build_display(
        flattened_parts,
        blank_lines_before=blank_lines_before,
        blank_lines_after=blank_lines_after,
        prompt_after=prompt_after,
        prompt_parts=prompt_parts,
        starts_on_new_line=starts_on_new_line,
    )


def display_text(
    text: str,
    *,
    fg: str = "bright_white",
    bold: bool = False,
    blank_lines_before: int = 1,
    blank_lines_after: int = 0,
    prompt_after: bool = False,
    prompt_parts: list[dict] | None = None
) -> dict:
    return build_display(
        [build_part(text, fg, bold)],
        blank_lines_before=blank_lines_before,
        blank_lines_after=blank_lines_after,
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
    return build_display([], blank_lines_before=0, prompt_after=prompt_after, prompt_parts=prompt_parts)


def display_force_prompt(session: ClientSession) -> dict:
    return build_display(
        [],
        blank_lines_before=0,
        blank_lines_after=1,
        prompt_after=True,
        prompt_parts=build_prompt_parts(session),
    )


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
    caps = get_player_resource_caps(session)
    me_condition, me_condition_color = get_health_condition(session.status.hit_points, caps["hit_points"])
    engaged_entity = get_engaged_entity(session)

    parts = [
        build_part("You are in ", "bright_white"),
        build_part(session.player.current_room_id, "bright_green", True),
        build_part(". Class: ", "bright_white"),
        build_part(session.player.class_id or "unassigned", "bright_cyan", True),
        build_part(". Level: ", "bright_white"),
        build_part(str(max(1, int(session.player.level))), "bright_magenta", True),
        build_part(". XP: ", "bright_white"),
        build_part(str(max(0, int(session.player.experience_points))), "bright_cyan", True),
        build_part(" (to next ", "bright_white"),
        build_part(str(get_xp_to_next_level(session.player.experience_points)), "bright_cyan", True),
        build_part(")", "bright_white"),
        build_part(". Attributes: ", "bright_white"),
        build_part(
            ", ".join(
                f"{attribute_id.upper()} {value}"
                for attribute_id, value in sorted(session.player.attributes.items())
            ) or "none",
            "bright_yellow",
            True,
        ),
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

    rows = [[str(wear_slot), str(item.name)] for wear_slot, item in worn_items]
    parts = build_menu_table_parts(
        "Worn Equipment",
        ["Slot", "Item"],
        rows,
        column_colors=["bright_cyan", "bright_magenta"],
        column_alignments=["left", "left"],
        empty_message="Nothing is worn.",
    )

    return build_display(parts, prompt_after=prompt_after, prompt_parts=prompt_parts)


def _item_highlight_color(item) -> str:
    return "bright_magenta" if is_item_equippable(item) else "bright_yellow"


def display_inventory(session: ClientSession) -> dict:
    prompt_after, prompt_parts = resolve_prompt(session, True)
    inventory_items = list(session.inventory_items.values())
    inventory_items.sort(key=lambda item: item.name.lower())

    def _stack_counts(items: list) -> list[tuple[str, str, int]]:
        counts: dict[str, int] = {}
        display_names: dict[str, str] = {}
        display_colors: dict[str, str] = {}
        order: list[str] = []

        for item in items:
            name = str(getattr(item, "name", "")).strip()
            normalized = name.lower()
            if not normalized:
                continue
            if normalized not in counts:
                counts[normalized] = 0
                display_names[normalized] = name
                display_colors[normalized] = _item_highlight_color(item)
                order.append(normalized)
            counts[normalized] += 1

        return [(display_names[key], display_colors[key], counts[key]) for key in order]

    inventory_stacks = _stack_counts(inventory_items)
    rows = [[item_name, str(count)] for item_name, _, count in inventory_stacks]
    row_cell_colors = [[item_color, "bright_cyan"] for _, item_color, _ in inventory_stacks]
    parts = build_menu_table_parts(
        "Inventory",
        ["Item", "Qty"],
        rows,
        column_colors=["bright_cyan", "bright_cyan"],
        row_cell_colors=row_cell_colors,
        column_alignments=["left", "right"],
        empty_message="Inventory is empty.",
    )

    return build_display(parts, prompt_after=prompt_after, prompt_parts=prompt_parts)


def _find_room_merchant(session: ClientSession | None):
    if session is None:
        return None

    room_id = str(getattr(session.player, "current_room_id", "")).strip()
    if not room_id:
        return None

    merchants = [
        entity
        for entity in list_room_entities(session, room_id)
        if getattr(entity, "is_alive", False) and bool(getattr(entity, "is_merchant", False))
    ]
    merchants.sort(key=lambda entity: str(getattr(entity, "name", "")).lower())
    return merchants[0] if merchants else None


def _merchant_quote_parts(merchant_name: str, quote: str) -> list[dict]:
    return [
        build_part(merchant_name, "bright_white", False),
        build_part(' says, "', "bright_white"),
        build_part(quote, "bright_white", False),
        build_part('"', "bright_white"),
    ]


def _build_lore_error_parts(message: str, session: ClientSession | None = None) -> list[dict]:
    cleaned = str(message).strip()
    lowered = cleaned.lower()
    merchant = _find_room_merchant(session)

    if merchant is not None:
        merchant_name = str(getattr(merchant, "name", "Merchant")).strip() or "Merchant"
        if "not sold here" in lowered or "no longer available" in lowered:
            return _merchant_quote_parts(merchant_name, "I'm sorry, I don't have that item.")
        if "out of stock" in lowered:
            return _merchant_quote_parts(merchant_name, "I'm afraid we've sold the last of that for now.")
        if "need " in lowered and " coins" in lowered:
            return _merchant_quote_parts(merchant_name, "You'll need a heavier purse for that one.")
        if "doesn't exist in your inventory" in lowered:
            return _merchant_quote_parts(merchant_name, "I can only bargain for what you are actually carrying.")

    if lowered.startswith("usage:"):
        usage_text = cleaned.split(":", 1)[1].strip() if ":" in cleaned else cleaned
        return [
            build_part("You pause, trying to recall the proper form: ", "bright_white"),
            build_part(usage_text, "bright_white", False),
        ]

    if "unknown command" in lowered:
        return [build_part("Those words carry no meaning here.", "bright_white", False)]
    if "not enough mana" in lowered:
        return [build_part("Your inner reserves are too thin for that working.", "bright_white", False)]
    if "not enough vigor" in lowered:
        return [build_part("Your body lacks the vigor for that effort just now.", "bright_white", False)]
    if "you are not engaged with anything" in lowered:
        return [build_part("No foe presently presses you.", "bright_white", False)]
    if "already fighting" in lowered:
        return [build_part("You are already locked in battle.", "bright_white", False)]
    if "no target named" in lowered:
        return [build_part("No such figure stands here before you.", "bright_white", False)]
    if "doesn't exist in your inventory" in lowered:
        return [build_part("You search your belongings, but find nothing of the sort.", "bright_white", False)]
    if "cannot be used" in lowered or "cannot be equipped" in lowered or "cannot be worn" in lowered or "cannot be wielded" in lowered or "cannot be held" in lowered:
        return [build_part("That would not serve you in that way.", "bright_white", False)]
    if "there are no coins on the ground" in lowered:
        return [build_part("Not a single coin glints at your feet.", "bright_white", False)]
    if "no corpse matching" in lowered:
        return [build_part("No such corpse lies here.", "bright_white", False)]
    if "cannot go" in lowered or "destination room not found" in lowered:
        return [build_part("The way does not open for you there.", "bright_white", False)]
    if "current room not found" in lowered:
        return [build_part("The world around you wavers strangely for a moment.", "bright_white", False)]

    if not cleaned:
        cleaned = "Something feels amiss."

    if cleaned[-1] not in ".!?":
        cleaned += "."

    return [
        build_part("A warning stirs within you: ", "bright_white"),
        build_part(cleaned, "bright_white", False),
    ]


def display_error(message: str, session: ClientSession | None = None) -> dict:
    prompt_after = False
    prompt_parts: list[dict] | None = None

    if session is not None:
        prompt_after, prompt_parts = resolve_prompt(session, True)

    return build_display(
        _build_lore_error_parts(message, session),
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
        blank_lines_before=0,
        blank_lines_after=1,
        prompt_after=False,
        starts_on_new_line=True
    )


def _scan_visible_hostiles(session: ClientSession, room_id: str) -> list:
    visible = [
        entity
        for entity in list_room_entities(session, room_id)
        if entity.is_alive and not bool(getattr(entity, "is_ally", False)) and not bool(getattr(entity, "is_peaceful", False))
    ]
    visible.sort(key=lambda entity: (entity.name.lower(), entity.spawn_sequence))
    return visible


def _append_scan_hostile_summary(parts: list[dict], entities: list, *, prefix: str = "Enemies: ") -> bool:
    if not entities:
        return False

    summarized: list[dict[str, object]] = []
    for entity in entities:
        normalized_name = entity.name.strip().lower()
        if summarized and str(summarized[-1]["normalized_name"]) == normalized_name:
            summarized[-1]["count"] = int(summarized[-1]["count"]) + 1
            continue

        summarized.append({
            "normalized_name": normalized_name,
            "name": entity.name,
            "count": 1,
        })

    if prefix:
        parts.append(build_part(prefix, "bright_white", True))

    for index, entry in enumerate(summarized):
        if index > 0:
            parts.append(build_part(", ", "bright_white"))

        parts.append(build_part(str(entry["name"]), "bright_red", True))
        count = int(entry["count"])
        if count > 1:
            parts.append(build_part(f" [{count}]", "bright_cyan", True))

    return True


def display_exits(session: ClientSession, room: Room) -> dict:
    prompt_after, prompt_parts = resolve_prompt(session, True)
    exit_items = sorted(room.exits.items(), key=lambda item: _direction_sort_key(item[0]))

    parts: list[dict] = [
        build_part(_panel_title_line("Exits"), "bright_cyan", True),
        build_part("\n"),
        build_part(_panel_divider(), "bright_black"),
    ]

    if not exit_items:
        parts.extend([
            build_part("\n"),
            build_part("No visible exits.", "bright_white"),
        ])
    else:
        direction_width = max(len(str(direction).strip().title()) for direction, _ in exit_items)
        for direction, destination_room_id in exit_items:
            destination_room = get_room(destination_room_id)
            destination_label = destination_room.title if destination_room is not None else str(destination_room_id)
            parts.extend([
                build_part("\n"),
                build_part(f"[{_direction_short_label(direction)}]", "bright_yellow", True),
                build_part(" ", "bright_white"),
                build_part(str(direction).strip().title().ljust(direction_width), "bright_cyan", True),
                build_part(" -> ", "bright_black"),
                build_part(destination_label, "bright_green", True),
            ])

            nearby_hostiles = _scan_visible_hostiles(session, destination_room_id)
            if nearby_hostiles:
                parts.append(build_part("  -  ", "bright_black"))
                _append_scan_hostile_summary(parts, nearby_hostiles, prefix="")

    visible_enemies = _scan_visible_hostiles(session, room.room_id)
    if visible_enemies:
        parts.extend([
            build_part("\n"),
            build_part(_panel_divider(), "bright_black"),
            build_part("\n"),
        ])
        _append_scan_hostile_summary(parts, visible_enemies, prefix="Here: ")

    return build_display(parts, blank_lines_before=0, prompt_after=prompt_after, prompt_parts=prompt_parts)


def _summarize_entity_gear(entity) -> list[str]:
    visible_items: list[str] = []

    main_template_id = str(getattr(entity, "main_hand_weapon_template_id", "")).strip()
    if main_template_id:
        template = get_gear_template_by_id(main_template_id)
        item_name = str(template.get("name", "Weapon")).strip() if template else main_template_id
        visible_items.append(f"Main Hand: {item_name}")

    off_template_id = str(getattr(entity, "off_hand_weapon_template_id", "")).strip()
    if off_template_id:
        template = get_gear_template_by_id(off_template_id)
        item_name = str(template.get("name", "Off-hand")).strip() if template else off_template_id
        visible_items.append(f"Off Hand: {item_name}")

    return visible_items


def _summarize_player_gear(target_session: ClientSession) -> list[str]:
    return [f"{slot.title()}: {item.name}" for slot, item in list_worn_items(target_session)]


def _display_look_summary(
    session: ClientSession,
    *,
    title: str,
    title_color: str,
    condition_text: str,
    condition_color: str,
    gear_summary: list[str],
) -> dict:
    prompt_after, prompt_parts = resolve_prompt(session, True)
    parts = [
        build_part(_panel_title_line(title), title_color, True),
        build_part("\n"),
        build_part(_panel_divider(), "bright_black"),
        build_part("\n"),
        build_part("Condition: ", "bright_white", True),
        build_part(condition_text.title(), condition_color, True),
        build_part("\n"),
        build_part("Gear:", "bright_white", True),
    ]

    if gear_summary:
        for gear_line in gear_summary:
            parts.extend([
                build_part("\n"),
                build_part(" - ", "bright_white"),
                build_part(gear_line, "bright_magenta", True),
            ])
    else:
        parts.extend([
            build_part("\n"),
            build_part("No obvious gear.", "bright_white"),
        ])

    return build_display(parts, blank_lines_before=1, prompt_after=prompt_after, prompt_parts=prompt_parts)


def display_entity_summary(session: ClientSession, entity) -> dict:
    condition_text, condition_color = get_entity_condition(entity)
    return _display_look_summary(
        session,
        title=entity.name,
        title_color="bright_green",
        condition_text=condition_text,
        condition_color=condition_color,
        gear_summary=_summarize_entity_gear(entity),
    )


def display_player_summary(session: ClientSession, target_session: ClientSession) -> dict:
    caps = get_player_resource_caps(target_session)
    condition_text, condition_color = get_health_condition(target_session.status.hit_points, caps["hit_points"])
    target_name = target_session.authenticated_character_name.strip() or "Player"
    return _display_look_summary(
        session,
        title=target_name,
        title_color="bright_cyan",
        condition_text=condition_text,
        condition_color=condition_color,
        gear_summary=_summarize_player_gear(target_session),
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
            parts.extend([
                build_part("\n"),
                build_part(" - ", "bright_white"),
                build_part(entity.name, bold=True),
            ])

    other_players = list_authenticated_room_players(room.room_id, exclude_client_id=session.client_id)
    if other_players:
        parts.extend([
            build_part("\n"),
            build_part("\n"),
            build_part("Players here:", "bright_white", True),
        ])

        for other_player in other_players:
            player_name = other_player.authenticated_character_name.strip() or "Unknown"
            parts.extend([
                build_part("\n"),
                build_part(" - ", "bright_white"),
                build_part(player_name, "bright_cyan", True),
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
    room_item_colors: dict[str, str] = {}
    room_item_order: list[str] = []
    for item in room_items:
        normalized = item.name.strip().lower()
        if not normalized:
            continue
        if normalized not in room_item_counts:
            room_item_counts[normalized] = 0
            room_item_names[normalized] = item.name
            room_item_colors[normalized] = _item_highlight_color(item)
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
                build_part(room_item_names[item_key], room_item_colors[item_key], True),
            ])
            count = room_item_counts[item_key]
            if count > 1:
                parts.extend([
                    build_part(" ", "bright_white"),
                    build_part(f"[{count}]", "bright_cyan", True),
                ])

    return build_display(parts, prompt_after=prompt_after, prompt_parts=prompt_parts)
