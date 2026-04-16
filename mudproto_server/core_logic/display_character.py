from attribute_config import get_affect_template_by_id, get_player_class_by_id, load_attributes, player_class_uses_mana
from equipment_logic import get_player_effective_attributes, list_worn_items
from experience import get_xp_to_next_level
from item_logic import _item_highlight_color
from models import ClientSession
from player_resources import get_player_resource_caps
from world import get_room

from display_core import build_display, build_menu_table_parts, build_part, newline_part, with_leading_blank_lines
from display_feedback import resolve_prompt_default


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
        return "display_character.resource.empty"

    ratio = max(0.0, min(1.0, float(current) / float(maximum)))
    if ratio <= 0.2:
        return "display_character.resource.low"
    if ratio <= 0.5:
        return "display_character.resource.medium"
    return "display_character.resource.high"


def _resolve_posture_label(session: ClientSession) -> str:
    if bool(getattr(session, "is_sleeping", False)):
        return "Sleeping"
    if bool(getattr(session, "is_resting", False)):
        return "Resting"
    if bool(getattr(session, "is_sitting", False)):
        return "Sitting"
    return "Standing"


def _resolve_effect_name(effect) -> str:
    spell_name = str(getattr(effect, "spell_name", "")).strip()
    if spell_name:
        return spell_name

    affect_name = str(getattr(effect, "affect_name", "")).strip()
    if affect_name:
        return affect_name

    return "Effect"


def _resolve_effect_label(effect) -> str:
    effect_name = _resolve_effect_name(effect).strip().lower()
    template_name = str(getattr(effect, "affect_template_name", "")).strip()
    if not template_name:
        affect_id = str(getattr(effect, "affect_id", "")).strip().lower()
        if affect_id:
            affect_template = get_affect_template_by_id(affect_id)
            if isinstance(affect_template, dict):
                template_name = str(affect_template.get("name", "")).strip()
    if template_name and template_name.strip().lower() != effect_name:
        return template_name
    return ""


def _format_effect_remaining_duration(effect) -> str:
    effect_mode = str(
        getattr(effect, "support_mode", getattr(effect, "affect_mode", "timed"))
    ).strip().lower() or "timed"
    if effect_mode == "battle_rounds":
        rounds = max(0, int(getattr(effect, "remaining_rounds", 0)))
        label = "round" if rounds == 1 else "rounds"
        return f"{rounds} {label}"

    if effect_mode == "timed":
        hours = max(0, int(getattr(effect, "remaining_hours", 0)))
        label = "hour" if hours == 1 else "hours"
        return f"{hours} {label}"

    return "lingering"


def display_score(session: ClientSession) -> dict:
    prompt_after, prompt_parts = resolve_prompt_default(session, True)
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
    effective_attributes = get_player_effective_attributes(session)
    for attribute in configured_attributes:
        attribute_id = str(attribute.get("attribute_id", "")).strip().lower()
        if not attribute_id:
            continue
        attribute_name = str(attribute.get("name", attribute_id)).strip() or attribute_id
        base_value = int(session.player.attributes.get(attribute_id, 0))
        value = int(effective_attributes.get(attribute_id, base_value))
        bonus = value - base_value
        suffix = f" ({bonus:+d})" if bonus else ""
        attribute_line_texts.append(f" - {attribute_name} ({attribute_id.upper()}): {value}{suffix}")

    active_effects = sorted(
        list(session.active_support_effects) + list(session.active_affects),
        key=lambda effect: _resolve_effect_name(effect).lower(),
    )
    effect_line_texts: list[str] = []
    if not active_effects:
        effect_line_texts.append(" - None")
    else:
        for effect in active_effects:
            effect_name = _resolve_effect_name(effect)
            effect_label = _resolve_effect_label(effect)
            duration_text = _format_effect_remaining_duration(effect)
            if effect_label:
                effect_line_texts.append(f" - {effect_name} ({effect_label}, {duration_text} remaining)")
            else:
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
        build_part(title_line, "display_character.ledger.title", True),
        newline_part(),
        build_part(divider, "display_character.ledger.divider"),
        newline_part(),
        build_part("Name: ", "display_character.label"),
        build_part(character_name, "display_character.name_value", True),
        build_part("   Class: ", "display_character.label"),
        build_part(class_name, "display_character.class_value", True),
        build_part("   Level: ", "display_character.label"),
        build_part(level_text, "display_character.level_value", True),
        newline_part(),
        build_part("Location: ", "display_character.label"),
        build_part(room_name, "display_character.location_value", True),
        newline_part(),
        build_part("Posture: ", "display_character.label"),
        build_part(posture_label, "display_character.posture_value", True),
        newline_part(),
        build_part(divider, "display_character.ledger.divider"),
        newline_part(),
        build_part("Health: ", "display_character.label"),
        build_part(f"{hp_now}/{hp_cap}", _resource_color(hp_now, hp_cap), True),
        build_part("   Vigor: ", "display_character.label"),
        build_part(f"{vigor_now}/{vigor_cap}", _resource_color(vigor_now, vigor_cap), True),
    ]

    if show_mana:
        parts.extend([
            build_part("   Mana: ", "display_character.label"),
            build_part(f"{mana_now}/{mana_cap}", _resource_color(mana_now, mana_cap), True),
        ])

    parts.extend([
        newline_part(),
        build_part("Coins: ", "display_character.label"),
        build_part(coins_text, "display_character.coins_value", True),
        newline_part(),
        build_part("Experience: ", "display_character.label"),
        build_part(str(xp_total), "display_character.xp_value", True),
        build_part("   To Next Level: ", "display_character.label"),
        build_part(str(xp_to_next), "display_character.xp_next_value", True),
        newline_part(),
        build_part(divider, "display_character.ledger.divider"),
        newline_part(),
        build_part("Attributes", "display_character.label", True),
    ])

    for attribute in configured_attributes:
        attribute_id = str(attribute.get("attribute_id", "")).strip().lower()
        if not attribute_id:
            continue
        attribute_name = str(attribute.get("name", attribute_id)).strip() or attribute_id
        base_value = int(session.player.attributes.get(attribute_id, 0))
        value = int(effective_attributes.get(attribute_id, base_value))
        bonus = value - base_value
        parts.extend([
            newline_part(),
            build_part(" - ", "display_character.label"),
            build_part(attribute_name, "display_character.attribute.name", True),
            build_part(" (", "display_character.label"),
            build_part(attribute_id.upper(), "display_character.attribute.code", True),
            build_part("): ", "display_character.label"),
            build_part(str(value), "display_character.attribute.value", True),
        ])
        if bonus:
            parts.extend([
                build_part(" (", "display_character.label"),
                build_part(f"{bonus:+d}", "display_character.attribute.bonus", True),
                build_part(")", "display_character.label"),
            ])

    parts.extend([
        newline_part(),
        build_part(divider, "display_character.ledger.divider"),
        newline_part(),
        build_part("Active Effects", "display_character.label", True),
    ])

    if not active_effects:
        parts.extend([
            newline_part(),
            build_part(" - None", "display_character.effects.empty"),
        ])
    else:
        for effect in active_effects:
            effect_name = _resolve_effect_name(effect)
            effect_label = _resolve_effect_label(effect)
            duration_text = _format_effect_remaining_duration(effect)
            parts.extend([
                newline_part(),
                build_part(" - ", "display_character.label"),
                build_part(effect_name, "display_character.effects.name", True),
                build_part(" (", "display_character.label"),
            ])
            if effect_label:
                parts.extend([
                    build_part(effect_label, "display_character.effects.type", True),
                    build_part(", ", "display_character.label"),
                ])
            parts.extend([
                build_part(duration_text, "display_character.effects.remaining", True),
                build_part(" remaining)", "display_character.label"),
            ])

    return build_display(with_leading_blank_lines(parts), prompt_after=prompt_after, prompt_parts=prompt_parts)


def display_equipment(session: ClientSession) -> dict:
    prompt_after, prompt_parts = resolve_prompt_default(session, True)
    worn_items = list_worn_items(session)
    rows = [[str(wear_slot), str(item.name)] for wear_slot, item in worn_items]
    parts = build_menu_table_parts(
        "Worn Equipment",
        ["Slot", "Item"],
        rows,
        column_colors=["display_character.equipment.slot_column", "display_character.equipment.item_column"],
        column_alignments=["left", "left"],
        empty_message="Nothing is worn.",
    )

    parts = with_leading_blank_lines(parts)

    return build_display(parts, prompt_after=prompt_after, prompt_parts=prompt_parts)


def display_inventory(session: ClientSession) -> dict:
    prompt_after, prompt_parts = resolve_prompt_default(session, True)
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
    row_cell_colors = [[item_color, "display_character.inventory.qty_column"] for _, item_color, _ in inventory_stacks]
    parts = build_menu_table_parts(
        "Inventory",
        ["Item", "Qty"],
        rows,
        column_colors=["display_character.equipment.slot_column", "display_character.inventory.qty_column"],
        row_cell_colors=row_cell_colors,
        column_alignments=["left", "right"],
        empty_message="Inventory is empty.",
    )

    parts = with_leading_blank_lines(parts)

    return build_display(parts, prompt_after=prompt_after, prompt_parts=prompt_parts)
