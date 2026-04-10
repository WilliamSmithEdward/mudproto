from assets import get_gear_template_by_id
from attribute_config import get_player_class_by_id, load_attributes
from combat_state import get_engaged_entity, get_entity_condition, get_health_condition
from equipment_logic import list_worn_items
from experience import get_xp_to_next_level
from inventory import is_item_equippable
from models import ClientSession
from player_resources import get_player_resource_caps
from session_registry import list_authenticated_room_players
from targeting_entities import list_room_corpses, list_room_entities
from world import Room, get_room

from display_core import (
    _panel_divider,
    _panel_title_line,
    build_display,
    build_menu_table_parts,
    build_part,
)
from display_feedback import _direction_short_label, _direction_sort_key, resolve_prompt


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
    prompt_after, prompt_parts = resolve_prompt(session, True)
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
        build_part(coins_text, "bright_cyan", True),
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


def _scan_visible_hostiles(session: ClientSession, room_id: str) -> list:
    visible = [
        entity
        for entity in list_room_entities(session, room_id)
        if entity.is_alive and not bool(getattr(entity, "is_ally", False)) and not bool(getattr(entity, "is_peaceful", False))
    ]
    visible.sort(key=lambda entity: (entity.name.lower(), entity.spawn_sequence))
    return visible


def _scan_visible_players(session: ClientSession, room_id: str) -> list[ClientSession]:
    visible = list_authenticated_room_players(room_id, exclude_client_id=session.client_id)
    visible.sort(key=lambda player_session: (player_session.authenticated_character_name.lower(), player_session.client_id))
    return visible


def _append_scan_hostile_summary(parts: list[dict], entities: list, *, prefix: str = "Enemies: ") -> bool:
    if not entities:
        return False

    summarized: list[dict[str, str | int]] = []
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


def _append_scan_player_summary(parts: list[dict], players: list[ClientSession], *, prefix: str = "Players: ") -> bool:
    if not players:
        return False

    summarized: list[dict[str, str | int]] = []
    for player_session in players:
        player_name = player_session.authenticated_character_name.strip() or "Unknown"
        normalized_name = player_name.lower()
        if summarized and str(summarized[-1]["normalized_name"]) == normalized_name:
            summarized[-1]["count"] = int(summarized[-1]["count"]) + 1
            continue

        summarized.append({
            "normalized_name": normalized_name,
            "name": player_name,
            "count": 1,
        })

    if prefix:
        parts.append(build_part(prefix, "bright_white", True))

    for index, entry in enumerate(summarized):
        if index > 0:
            parts.append(build_part(", ", "bright_white"))

        parts.append(build_part(str(entry["name"]), "bright_cyan", True))
        count = int(entry["count"])
        if count > 1:
            parts.append(build_part(f" [{count}]", "bright_yellow", True))

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
            nearby_players = _scan_visible_players(session, destination_room_id)
            if nearby_hostiles or nearby_players:
                parts.append(build_part("  -  ", "bright_black"))
                appended_summary = False
                if nearby_hostiles:
                    appended_summary = _append_scan_hostile_summary(parts, nearby_hostiles, prefix="Enemies: ")
                if nearby_players:
                    if appended_summary:
                        parts.append(build_part("  |  ", "bright_black"))
                    _append_scan_player_summary(parts, nearby_players, prefix="Players: ")

    visible_enemies = _scan_visible_hostiles(session, room.room_id)
    visible_players = _scan_visible_players(session, room.room_id)
    if visible_enemies or visible_players:
        parts.extend([
            build_part("\n"),
            build_part(_panel_divider(), "bright_black"),
            build_part("\n"),
            build_part("Here: ", "bright_white", True),
        ])
        appended_summary = False
        if visible_enemies:
            appended_summary = _append_scan_hostile_summary(parts, visible_enemies, prefix="Enemies: ")
        if visible_players:
            if appended_summary:
                parts.append(build_part("  |  ", "bright_black"))
            _append_scan_player_summary(parts, visible_players, prefix="Players: ")

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


def _display_character_name(target_session: ClientSession) -> str:
    return str(target_session.authenticated_character_name).strip() or "Unknown"


def _resolve_entity_engagement_target_name(current_session: ClientSession, entity) -> str | None:
    entity_id = str(getattr(entity, "entity_id", "")).strip()
    if not entity_id:
        return None

    if entity_id in current_session.combat.engaged_entity_ids:
        return _display_character_name(current_session)

    room_players = list_authenticated_room_players(
        str(getattr(entity, "room_id", "")).strip(),
        exclude_client_id=current_session.client_id,
    )
    for player_session in room_players:
        if entity_id in player_session.combat.engaged_entity_ids:
            return _display_character_name(player_session)
    return None


def _resolve_player_engagement_target_name(target_session: ClientSession) -> str | None:
    engaged_entity = get_engaged_entity(target_session)
    if engaged_entity is None:
        return None
    if not getattr(engaged_entity, "is_alive", False):
        return None
    if str(getattr(engaged_entity, "room_id", "")).strip() != str(target_session.player.current_room_id).strip():
        return None
    return str(getattr(engaged_entity, "name", "")).strip() or "Unknown"


def _append_room_engagement_parts(parts: list[dict], target_name: str | None, *, is_you: bool = False) -> None:
    if not target_name:
        return

    verb_text = "Fighting " if is_you else "fighting "
    label_text = "YOU!" if is_you else target_name
    parts.extend([
        build_part(" (", "bright_white"),
        build_part(verb_text, "bright_white"),
        build_part(label_text, "bright_yellow", True),
        build_part(")", "bright_white"),
    ])


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
            engagement_target = _resolve_entity_engagement_target_name(session, entity)
            _append_room_engagement_parts(
                parts,
                engagement_target,
                is_you=bool(engagement_target) and engagement_target == _display_character_name(session),
            )

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
            _append_room_engagement_parts(parts, _resolve_player_engagement_target_name(other_player))

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
