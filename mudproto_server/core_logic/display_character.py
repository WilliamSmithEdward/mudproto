from attribute_config import get_player_class_by_id, load_attributes, player_class_uses_mana
from equipment_logic import list_worn_items
from experience import get_xp_to_next_level
from item_logic import _item_highlight_color
from models import ClientSession
from player_resources import get_player_resource_caps
from world import get_room

from display_core import build_display, build_menu_table_parts, build_part, newline_part, with_leading_blank_lines
from display_feedback import resolve_prompt


PANEL_INNER_WIDTH = 34


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


def _resolve_posture_label(session: ClientSession) -> str:
    if bool(getattr(session, "is_sleeping", False)):
        return "Sleeping"
    if bool(getattr(session, "is_resting", False)):
        return "Resting"
    if bool(getattr(session, "is_sitting", False)):
        return "Sitting"
    return "Standing"


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


def display_score(session: ClientSession) -> dict:
    prompt_after, prompt_parts = resolve_prompt(session, True, prompt_gap_lines=2)
    caps = get_player_resource_caps(session)
    xp_total = max(0, int(session.player.experience_points))
    xp_to_next = get_xp_to_next_level(xp_total)
    class_name = _resolve_player_class_name(session.player.class_id)
    character_name = session.authenticated_character_name or "Unknown"
    room = get_room(session.player.current_room_id)
    room_name = room.title if room is not None else "Unknown"
    posture_label = _resolve_posture_label(session)

    hp_now = max(0, int(session.status.hit_points))
    hp_cap = max(1, int(caps["hit_points"]))
    vigor_now = max(0, int(session.status.vigor))
    vigor_cap = max(1, int(caps["vigor"]))
    mana_now = max(0, int(session.status.mana))
    mana_cap = max(0, int(caps["mana"]))
    show_mana = player_class_uses_mana(session.player.class_id) and mana_cap > 0

    level_text = str(max(1, int(session.player.level)))
    coins_text = str(max(0, int(session.status.coins)))

    summary_line = f"Name: {character_name}   Class: {class_name}   Level: {level_text}"
    location_line = f"Location: {room_name}"
    posture_line = f"Posture: {posture_label}"
    resources_line = f"Health: {hp_now}/{hp_cap}   Vigor: {vigor_now}/{vigor_cap}"
    if show_mana:
        resources_line += f"   Mana: {mana_now}/{mana_cap}"
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
        len(posture_line),
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
        newline_part(),
        build_part(divider, "bright_black"),
        newline_part(),
        build_part("Name: ", "bright_white"),
        build_part(character_name, "bright_yellow", True),
        build_part("   Class: ", "bright_white"),
        build_part(class_name, "bright_cyan", True),
        build_part("   Level: ", "bright_white"),
        build_part(level_text, "bright_green", True),
        newline_part(),
        build_part("Location: ", "bright_white"),
        build_part(room_name, "bright_magenta", True),
        newline_part(),
        build_part("Posture: ", "bright_white"),
        build_part(posture_label, "bright_cyan", True),
        newline_part(),
        build_part(divider, "bright_black"),
        newline_part(),
        build_part("Health: ", "bright_white"),
        build_part(f"{hp_now}/{hp_cap}", _resource_color(hp_now, hp_cap), True),
        build_part("   Vigor: ", "bright_white"),
        build_part(f"{vigor_now}/{vigor_cap}", _resource_color(vigor_now, vigor_cap), True),
    ]

    if show_mana:
        parts.extend([
            build_part("   Mana: ", "bright_white"),
            build_part(f"{mana_now}/{mana_cap}", _resource_color(mana_now, mana_cap), True),
        ])

    parts.extend([
        newline_part(),
        build_part("Coins: ", "bright_white"),
        build_part(coins_text, "bright_cyan", True),
        newline_part(),
        build_part("Experience: ", "bright_white"),
        build_part(str(xp_total), "bright_cyan", True),
        build_part("   To Next Level: ", "bright_white"),
        build_part(str(xp_to_next), "bright_green", True),
        newline_part(),
        build_part(divider, "bright_black"),
        newline_part(),
        build_part("Attributes", "bright_white", True),
    ])

    for attribute in configured_attributes:
        attribute_id = str(attribute.get("attribute_id", "")).strip().lower()
        if not attribute_id:
            continue
        attribute_name = str(attribute.get("name", attribute_id)).strip() or attribute_id
        value = int(session.player.attributes.get(attribute_id, 0))
        parts.extend([
            newline_part(),
            build_part(" - ", "bright_white"),
            build_part(attribute_name, "bright_cyan", True),
            build_part(" (", "bright_white"),
            build_part(attribute_id.upper(), "bright_yellow", True),
            build_part("): ", "bright_white"),
            build_part(str(value), "bright_green", True),
        ])

    parts.extend([
        newline_part(),
        build_part(divider, "bright_black"),
        newline_part(),
        build_part("Active Effects", "bright_white", True),
    ])

    if not active_effects:
        parts.extend([
            newline_part(),
            build_part(" - None", "bright_black"),
        ])
    else:
        for effect in active_effects:
            effect_name = str(getattr(effect, "spell_name", "Effect")).strip() or "Effect"
            duration_text = _format_effect_remaining_duration(effect)
            parts.extend([
                newline_part(),
                build_part(" - ", "bright_white"),
                build_part(effect_name, "bright_magenta", True),
                build_part(" (", "bright_white"),
                build_part(duration_text, "bright_yellow", True),
                build_part(" remaining)", "bright_white"),
            ])

    return build_display(with_leading_blank_lines(parts), prompt_after=prompt_after, prompt_parts=prompt_parts)


def display_equipment(session: ClientSession) -> dict:
    prompt_after, prompt_parts = resolve_prompt(session, True, prompt_gap_lines=2)
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

    parts = with_leading_blank_lines(parts)

    return build_display(parts, prompt_after=prompt_after, prompt_parts=prompt_parts)


def display_inventory(session: ClientSession) -> dict:
    prompt_after, prompt_parts = resolve_prompt(session, True, prompt_gap_lines=2)
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

    parts = with_leading_blank_lines(parts)

    return build_display(parts, prompt_after=prompt_after, prompt_parts=prompt_parts)
