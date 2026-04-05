import random
import re

from attribute_config import get_player_class_by_id, load_attributes, load_item_usage_config
from assets import get_item_template_by_id, load_item_templates, load_skills, load_spells
from combat import (
    end_combat,
    get_engaged_entity,
    maybe_auto_engage_current_room,
)
from display import (
    build_menu_table_parts,
    build_line,
    build_part,
    parts_to_lines,
    display_command_result,
    display_error,
    display_prompt,
    display_room,
)
from equipment import (
    HAND_BOTH,
    HAND_MAIN,
    HAND_OFF,
    equip_item,
    get_equipped_main_hand,
    get_equipped_off_hand,
    list_worn_items,
    resolve_equipped_selector,
    resolve_wear_slot_alias,
    unequip_item,
    wear_item,
)
from grammar import indefinite_article, resolve_player_pronouns, with_article
from inventory import (
    get_item_keywords,
    is_item_equippable,
    parse_item_selector,
)
from models import ClientSession, ItemState
from experience import get_xp_to_next_level
from player_resources import get_player_resource_caps
from settings import (
    FLEE_SUCCESS_CHANCE,
)
from sessions import apply_lag, enqueue_command, is_session_lagged, list_authenticated_room_players
from sessions import (
    connected_clients,
)
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


def initial_auth_prompt(session: ClientSession) -> OutboundMessage:
    from command_handlers.auth import initial_auth_prompt as _initial_auth_prompt

    return _initial_auth_prompt(session)


def login_prompt(session: ClientSession) -> OutboundMessage:
    from command_handlers.auth import login_prompt as _login_prompt

    return _login_prompt(session)


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


def _panel_divider() -> str:
    return "-" * PANEL_INNER_WIDTH


def _panel_title_line(title: str) -> str:
    return str(title).strip().center(PANEL_INNER_WIDTH)


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


def _parse_hand_and_selector(args: list[str]) -> tuple[str | None, str | None, str | None]:
    if not args:
        return None, None, "Usage: equip <selector> [main|off|both]"

    normalized = [arg.strip().lower() for arg in args if arg.strip()]
    hand_aliases = {
        "main": HAND_MAIN,
        "mainhand": HAND_MAIN,
        "main_hand": HAND_MAIN,
        "off": HAND_OFF,
        "offhand": HAND_OFF,
        "off_hand": HAND_OFF,
        "both": HAND_BOTH,
        "2h": HAND_BOTH,
        "twohand": HAND_BOTH,
        "twohands": HAND_BOTH,
        "two_hand": HAND_BOTH,
        "two_hands": HAND_BOTH,
    }

    hand: str | None = None
    selector_parts: list[str] = []
    for token in normalized:
        mapped_hand = hand_aliases.get(token)
        if mapped_hand is not None:
            hand = mapped_hand
            continue
        selector_parts.append(token)

    selector = ".".join(selector_parts).strip(".")
    if not selector:
        return None, None, "Usage: equip <selector> [main|off|both]"

    return hand, selector, None


def _parse_wear_selector_and_location(args: list[str]) -> tuple[str | None, str | None, str | None]:
    if not args:
        return None, None, "Usage: wear <selector> [location]"

    normalized = [arg.strip().lower() for arg in args if arg.strip()]
    if not normalized:
        return None, None, "Usage: wear <selector> [location]"

    selector_tokens = normalized
    wear_location: str | None = None

    # Try longest suffix first so both `right hand` and `right.hand` work.
    for suffix_len in (2, 1):
        if len(normalized) <= suffix_len:
            continue
        candidate_suffix = normalized[-suffix_len:]
        candidate_location = resolve_wear_slot_alias(" ".join(candidate_suffix))
        if candidate_location is None:
            continue
        wear_location = candidate_location
        selector_tokens = normalized[:-suffix_len]
        break

    selector = ".".join(selector_tokens).strip(".")
    if not selector:
        return None, None, "Usage: wear <selector> [location]"

    return selector, wear_location, None


def _parse_cast_spell(
    command_text: str,
    args: list[str],
    verb: str,
) -> tuple[str | None, str | None, str | None]:
    escaped_verb = re.escape(verb.strip())
    quoted_match = re.match(
        rf"^{escaped_verb}\s+(['\"])(.+?)\1(?:\s+(.+))?\s*$",
        command_text.strip(),
        re.IGNORECASE,
    )
    if quoted_match is not None:
        spell_name = quoted_match.group(2).strip()
        target_name = (quoted_match.group(3) or "").strip() or None
        if spell_name:
            return spell_name, target_name, None

    spell_name = " ".join(args).strip()
    if (
        len(spell_name) >= 2
        and spell_name[0] in {"'", '"'}
        and spell_name[-1] == spell_name[0]
    ):
        spell_name = spell_name[1:-1].strip()

    if not spell_name:
        return None, None, "Usage: cast 'spell name' [target]"

    return spell_name, None, None


def _parse_skill_use(
    args: list[str],
) -> tuple[str | None, str | None, str | None]:
    skill_name = " ".join(args).strip()
    if not skill_name:
        return None, None, "Usage: <skill> [target]"

    return skill_name, None, None


def _build_corpse_label(source_name: str) -> str:
    return f"{source_name} corpse"


def _display_corpse_examination(session: ClientSession, corpse) -> OutboundResult:
    rows: list[list[str]] = [["Coins", str(max(0, int(corpse.coins)))]]
    row_cell_colors: list[list[str]] = [["bright_cyan", "bright_cyan"]]

    loot_items = list(corpse.loot_items.values())
    loot_items.sort(key=lambda item: item.name.lower())
    if loot_items:
        item_counts: dict[str, int] = {}
        item_names: dict[str, str] = {}
        item_colors: dict[str, str] = {}
        item_order: list[str] = []

        for loot_item in loot_items:
            normalized_name = loot_item.name.strip().lower()
            if not normalized_name:
                continue
            if normalized_name not in item_counts:
                item_counts[normalized_name] = 0
                item_names[normalized_name] = loot_item.name
                item_colors[normalized_name] = _item_highlight_color(loot_item)
                item_order.append(normalized_name)
            item_counts[normalized_name] += 1

        for item_key in item_order:
            count = item_counts[item_key]
            item_label = item_names[item_key] if count == 1 else f"{item_names[item_key]} [{count}]"
            rows.append(["Item", item_label])
            row_cell_colors.append(["bright_magenta", item_colors[item_key]])
    else:
        rows.append(["Items", "None"])
        row_cell_colors.append(["bright_magenta", "bright_black"])

    parts = build_menu_table_parts(
        _build_corpse_label(corpse.source_name),
        ["Loot", "Contents"],
        rows,
        column_colors=["bright_cyan", "bright_white"],
        row_cell_colors=row_cell_colors,
        column_alignments=["left", "left"],
    )
    parts.extend([
        build_part("\n"),
        build_part("Commands: ", "bright_white"),
        build_part("get <item> <corpse>", "bright_yellow", True),
        build_part(", ", "bright_white"),
        build_part("get coins <corpse>", "bright_yellow", True),
        build_part(", ", "bright_white"),
        build_part("get all <corpse>", "bright_yellow", True),
    ])

    return display_command_result(session, parts)


def _normalize_item_look_selector(selector_text: str) -> tuple[str, bool]:
    cleaned = re.sub(r"\s+", " ", selector_text.strip())
    lowered = cleaned.lower()

    if lowered.startswith("at "):
        cleaned = cleaned[3:].strip()
        lowered = cleaned.lower()

    search_room = False
    for suffix in (" in the room", " in room", " on the ground", " on ground"):
        if lowered.endswith(suffix):
            cleaned = cleaned[:-len(suffix)].strip()
            search_room = True
            break

    return cleaned, search_room


def _resolve_item_location_label(session: ClientSession, item: ItemState, *, default_label: str = "Inventory") -> str:
    if (
        session.equipment.equipped_main_hand_id == item.item_id
        and session.equipment.equipped_off_hand_id == item.item_id
    ):
        return "Both hands"
    if session.equipment.equipped_main_hand_id == item.item_id:
        return "Main hand"
    if session.equipment.equipped_off_hand_id == item.item_id:
        return "Off hand"

    for wear_slot, worn_item_id in session.equipment.worn_item_ids.items():
        if worn_item_id == item.item_id:
            return f"Worn on {wear_slot.replace('_', ' ')}"

    if item.item_id in session.inventory_items:
        return "Inventory"

    return default_label


def _resolve_item_kind_label(item: ItemState) -> str:
    if is_item_equippable(item):
        return "Weapon" if item.slot == "weapon" else "Armor"
    return "Item"


def _format_item_wear_slots(item: ItemState) -> str:
    wear_slots = [str(slot).strip().lower() for slot in item.wear_slots if str(slot).strip()]
    if not wear_slots and str(item.wear_slot).strip():
        wear_slots = [str(item.wear_slot).strip().lower()]
    return ", ".join(slot.replace("_", " ").title() for slot in wear_slots)


def _display_item_examination(session: ClientSession, item: ItemState, *, default_location: str = "Inventory") -> OutboundResult:
    kind_label = _resolve_item_kind_label(item)
    location_label = _resolve_item_location_label(session, item, default_label=default_location)
    rows: list[list[str]] = [
        ["Type", kind_label],
        ["Location", location_label],
    ]

    if kind_label == "Weapon":
        weapon_type = str(getattr(item, "weapon_type", "") or "weapon").replace("_", " ").title()
        rows.append(["Weapon Type", weapon_type])
    elif kind_label == "Armor":
        wear_slot_label = _format_item_wear_slots(item)
        if wear_slot_label:
            rows.append(["Wear Slot", wear_slot_label])

    parts = build_menu_table_parts(
        str(getattr(item, "name", "Item")).strip() or "Item",
        ["Field", "Details"],
        rows,
        column_colors=["bright_cyan", "bright_white"],
        column_alignments=["left", "left"],
    )

    description = str(getattr(item, "description", "")).strip() or "No description is available for this item."
    parts.extend([
        build_part("\n"),
        build_part("Description", "bright_white", True),
        build_part("\n"),
        build_part(description, "bright_white"),
    ])

    return display_command_result(session, parts)


def _resolve_owned_item_selector(session: ClientSession, selector: str) -> tuple[ItemState | None, str | None, str | None]:
    requested_index, keywords, parse_error = parse_item_selector(selector)
    if parse_error is not None:
        return None, None, parse_error

    candidates: list[tuple[int, str, ItemState]] = []
    seen_item_ids: set[str] = set()

    for location_label, item in list_worn_items(session):
        if item.item_id in seen_item_ids:
            continue
        seen_item_ids.add(item.item_id)
        candidates.append((0, str(location_label).strip() or "equipped", item))

    for item in session.inventory_items.values():
        if item.item_id in seen_item_ids:
            continue
        seen_item_ids.add(item.item_id)
        candidates.append((1, "inventory", item))

    candidates.sort(key=lambda entry: (entry[0], entry[2].name.lower(), entry[2].item_id))

    matches: list[tuple[ItemState, str]] = []
    for _, location_label, item in candidates:
        item_keywords = get_item_keywords(item)
        if all(keyword in item_keywords for keyword in keywords):
            matches.append((item, location_label))

    if not matches:
        return None, None, f"You are not carrying or wearing anything matching '{selector}'."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, None, f"Only {len(matches)} match(es) found for '{selector}'."
        selected_item, location_label = matches[requested_index - 1]
        return selected_item, location_label, None

    selected_item, location_label = matches[0]
    return selected_item, location_label, None


def _resolve_room_ground_item_selector(session: ClientSession, room_id: str, selector: str) -> tuple[ItemState | None, str | None]:
    matches, requested_index, selector_error = _resolve_room_ground_matches(session, room_id, selector)
    if selector_error is not None:
        return None, selector_error

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} match(es) found for '{selector}'."
        return matches[requested_index - 1], None

    return matches[0], None


def _selector_prefix_matches_keywords(parts: list[str], keywords: set[str]) -> bool:
    if not parts or not keywords:
        return False
    return all(
        any(keyword.startswith(part) for keyword in keywords)
        for part in parts
    )


def _resolve_room_player_selector(session: ClientSession, selector_text: str) -> tuple[ClientSession | None, str | None]:
    normalized = selector_text.strip().lower()
    if not normalized:
        return None, "Provide a target selector."

    if normalized in {"me", "self", "myself"}:
        return session, None

    room_players = list_authenticated_room_players(session.player.current_room_id)
    if not room_players:
        return None, f"No player named '{selector_text}' is here."

    query_parts = [part for part in re.findall(r"[a-zA-Z0-9]+", normalized) if part]

    if "." not in normalized:
        exact_match: ClientSession | None = None
        partial_match: ClientSession | None = None
        for player_session in room_players:
            player_name = (player_session.authenticated_character_name or "").strip().lower()
            if not player_name:
                continue

            if player_name == normalized:
                exact_match = player_session
                break

            player_keywords = {token for token in re.findall(r"[a-zA-Z0-9]+", player_name) if token}
            if _selector_prefix_matches_keywords(query_parts, player_keywords) and partial_match is None:
                partial_match = player_session

        if exact_match is not None:
            return exact_match, None
        if partial_match is not None:
            return partial_match, None
        return None, f"No player named '{selector_text}' is here."

    parts = [part for part in normalized.split(".") if part]
    if not parts:
        return None, "Provide a target selector."

    requested_index: int | None = None
    if parts[0].isdigit():
        requested_index = int(parts[0])
        parts = parts[1:]
        if requested_index <= 0:
            return None, "Selector index must be 1 or greater."

    if not parts:
        return None, "Provide at least one selector keyword after the index."

    matches: list[ClientSession] = []
    for player_session in room_players:
        player_name = (player_session.authenticated_character_name or "").strip().lower()
        keywords = {token for token in re.findall(r"[a-zA-Z0-9]+", player_name) if token}
        if _selector_prefix_matches_keywords(parts, keywords):
            matches.append(player_session)

    if not matches:
        return None, f"No player named '{selector_text}' is here."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} player match(es) found for '{selector_text}'."
        return matches[requested_index - 1], None

    return matches[0], None


def _clear_follow_state(session: ClientSession) -> None:
    session.following_player_key = ""
    session.following_player_name = ""


def _find_followed_player_session(session: ClientSession) -> ClientSession | None:
    normalized_key = (session.following_player_key or "").strip().lower()
    if not normalized_key:
        return None

    for candidate in connected_clients.values():
        if not candidate.is_connected or candidate.disconnected_by_server or not candidate.is_authenticated:
            continue
        candidate_key = (candidate.player_state_key or candidate.client_id).strip().lower()
        if candidate_key == normalized_key:
            return candidate
    return None


def _would_create_follow_loop(session: ClientSession, target_session: ClientSession) -> bool:
    follower_key = (session.player_state_key or session.client_id).strip().lower()
    if not follower_key:
        return False

    seen_keys: set[str] = {follower_key}
    current: ClientSession | None = target_session
    while current is not None:
        current_key = (current.player_state_key or current.client_id).strip().lower()
        if not current_key:
            return False
        if current_key in seen_keys:
            return True

        seen_keys.add(current_key)
        next_key = (current.following_player_key or "").strip().lower()
        if not next_key:
            return False

        current = None
        for candidate in connected_clients.values():
            if not candidate.is_connected or candidate.disconnected_by_server or not candidate.is_authenticated:
                continue
            candidate_key = (candidate.player_state_key or candidate.client_id).strip().lower()
            if candidate_key == next_key:
                current = candidate
                break

    return False


def _resolve_inventory_selector(session: ClientSession, selector: str):
    requested_index, keywords, parse_error = parse_item_selector(selector)
    if parse_error is not None:
        return None, parse_error

    inventory_items = list(session.inventory_items.values())
    inventory_items.sort(key=lambda item: item.name.lower())

    matches = []
    for item in inventory_items:
        item_keywords = get_item_keywords(item)
        if all(keyword in item_keywords for keyword in keywords):
            matches.append(item)

    if not matches:
        return None, f"{selector} doesn't exist in inventory."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} match(es) found for '{selector}'."
        return matches[requested_index - 1], None

    return matches[0], None


def _resolve_misc_inventory_selector(session: ClientSession, selector: str):
    requested_index, keywords, parse_error = parse_item_selector(selector)
    if parse_error is not None:
        return None, parse_error

    misc_items = [
        item
        for item in session.inventory_items.values()
        if not is_item_equippable(item)
    ]
    misc_items.sort(key=lambda item: item.name.lower())

    matches = []
    for item in misc_items:
        item_keywords = get_item_keywords(item)
        if all(keyword in item_keywords for keyword in keywords):
            matches.append(item)

    if not matches:
        return None, f"{selector} doesn't exist in inventory."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} match(es) found for '{selector}'."
        return matches[requested_index - 1], None

    return matches[0], None


def _resolve_wear_inventory_selector(session: ClientSession, selector: str) -> tuple[ItemState | None, str | None]:
    selected_item, resolve_error = _resolve_inventory_selector(session, selector)
    if selected_item is None:
        return None, resolve_error
    if not is_item_equippable(selected_item):
        return None, f"{selected_item.name} cannot be worn."
    return selected_item, None


def _list_room_ground_items(session: ClientSession, room_id: str):
    room_items = list(session.room_ground_items.get(room_id, {}).values())
    room_items.sort(key=lambda item: (item.name.lower(), item.item_id))
    return room_items


def _resolve_room_ground_matches(session: ClientSession, room_id: str, selector: str):
    requested_index, keywords, parse_error = parse_item_selector(selector)
    if parse_error is not None:
        return [], None, parse_error

    matches = []
    for item in _list_room_ground_items(session, room_id):
        item_keywords = get_item_keywords(item)
        if all(keyword in item_keywords for keyword in keywords):
            matches.append(item)

    if not matches:
        return [], requested_index, f"No room item matches '{selector}'."

    return matches, requested_index, None


def _add_item_to_room_ground(session: ClientSession, room_id: str, item) -> None:
    room_items = session.room_ground_items.setdefault(room_id, {})
    room_items[item.item_id] = item


def _pickup_ground_item(session: ClientSession, room_id: str, item) -> None:
    """Move an item from room ground into player inventory."""
    session.room_ground_items.get(room_id, {}).pop(item.item_id, None)
    session.inventory_items[item.item_id] = item


def _find_item_template_for_misc_item(misc_item) -> dict | None:
    template_id = str(getattr(misc_item, "template_id", "")).strip()
    if template_id:
        template = get_item_template_by_id(template_id)
        if template is not None:
            return template

    normalized_item_name = misc_item.name.strip().lower()
    if not normalized_item_name:
        return None

    item_tokens = {token for token in re.findall(r"[a-zA-Z0-9]+", normalized_item_name) if token}
    for template in load_item_templates():
        template_name = str(template.get("name", "")).strip().lower()
        if template_name == normalized_item_name:
            return template

        keywords = [str(keyword).strip().lower() for keyword in template.get("keywords", [])]
        if keywords and all(keyword in item_tokens for keyword in keywords):
            return template

    return None


def _is_potion_template(template: dict) -> bool:
    template_name = str(template.get("name", "")).strip().lower()
    keywords = {
        str(keyword).strip().lower()
        for keyword in template.get("keywords", [])
        if str(keyword).strip()
    }
    return "potion" in keywords or "potion" in template_name


def _get_potion_cooldown_rounds() -> int:
    config = load_item_usage_config()
    potion_config = config.get("potion", {}) if isinstance(config, dict) else {}
    if not isinstance(potion_config, dict):
        return 0
    return max(0, int(potion_config.get("cooldown_rounds", 0)))


def _use_misc_item(session: ClientSession, selector: str) -> OutboundResult:
    if not selector.strip():
        return display_error("Usage: use <item>", session)

    misc_item, resolve_error = _resolve_misc_inventory_selector(session, selector)
    if misc_item is None:
        return display_error(resolve_error or f"No inventory item matches '{selector}'.", session)

    template = _find_item_template_for_misc_item(misc_item)
    if template is None:
        return display_error(f"{misc_item.name} cannot be used.", session)

    effect_type = str(template.get("effect_type", "restore")).strip().lower() or "restore"
    effect_target = str(template.get("effect_target", "")).strip().lower()
    effect_amount = max(0, int(template.get("effect_amount", 0)))
    use_lag_seconds = max(0.0, float(template.get("use_lag_seconds", 0.0)))

    if effect_type != "restore" or effect_amount <= 0:
        return display_error(f"{misc_item.name} cannot be used.", session)

    is_potion = _is_potion_template(template)
    potion_cooldown_key = "potion"
    if is_potion:
        remaining_rounds = int(session.combat.item_cooldowns.get(potion_cooldown_key, 0))
        if remaining_rounds > 0:
            return display_error(
                f"You must wait {remaining_rounds} more battle round(s) before using another potion.",
                session,
            )

    current_value = 0
    max_value = 0
    effect_label = ""
    caps = get_player_resource_caps(session)
    if effect_target == "hit_points":
        current_value = session.status.hit_points
        max_value = caps["hit_points"]
        effect_label = "HP"
    elif effect_target == "mana":
        current_value = session.status.mana
        max_value = caps["mana"]
        effect_label = "Mana"
    elif effect_target == "vigor":
        current_value = session.status.vigor
        max_value = caps["vigor"]
        effect_label = "Vigor"
    else:
        return display_error(f"{misc_item.name} cannot be used.", session)

    if current_value >= max_value:
        return display_error(f"Your {effect_label.lower()} is already full.", session)

    restored_amount = min(effect_amount, max_value - current_value)
    setattr(session.status, effect_target, current_value + restored_amount)
    session.inventory_items.pop(misc_item.item_id, None)

    if is_potion:
        cooldown_rounds = _get_potion_cooldown_rounds()
        if cooldown_rounds > 0:
            session.combat.item_cooldowns[potion_cooldown_key] = cooldown_rounds

    if use_lag_seconds > 0:
        try:
            apply_lag(session, use_lag_seconds)
        except RuntimeError:
            pass

    item_name = misc_item.name.strip().lower() or "item"
    item_article = indefinite_article(item_name)

    observer_action = str(template.get("observer_action", "")).strip()
    observer_context = str(template.get("observer_context", "")).strip()
    actor_name = session.authenticated_character_name or "Someone"

    if not observer_action:
        observer_action = f"{actor_name} uses {item_article} {item_name}."

    actor_subject_pronoun, actor_object_pronoun, actor_possessive_pronoun, _ = resolve_player_pronouns(
        actor_name=actor_name,
        actor_gender=session.player.gender,
    )
    observer_action = (
        observer_action
        .replace("[actor_name]", actor_name)
        .replace("[actor_subject]", actor_subject_pronoun)
        .replace("[actor_object]", actor_object_pronoun)
        .replace("[actor_possessive]", actor_possessive_pronoun)
    )

    if observer_context:
        observer_context = (
            observer_context
            .replace("[actor_name]", actor_name)
            .replace("[actor_subject]", actor_subject_pronoun)
            .replace("[actor_object]", actor_object_pronoun)
            .replace("[actor_possessive]", actor_possessive_pronoun)
        )

    result = display_command_result(session, [
        build_part("You use ", "bright_white"),
        build_part(f"{item_article} {item_name}", "bright_yellow", True),
        build_part(".", "bright_white"),
    ])

    payload = result.get("payload")
    if isinstance(payload, dict):
        room_parts = [build_part(observer_action, "bright_white")]
        if observer_context:
            room_parts.extend([
                build_part("\n", "bright_white"),
                build_part(observer_context, "bright_white"),
            ])
        payload["room_broadcast_lines"] = parts_to_lines(room_parts)

    return result


def _item_highlight_color(item) -> str:
    return "bright_magenta" if is_item_equippable(item) else "bright_yellow"


def _build_item_reference_parts(item, *, fg: str | None = None) -> list[dict]:
    article, _, item_name = with_article(item.name).partition(" ")
    item_color = fg or _item_highlight_color(item)
    return [
        build_part(f"{article} ", "bright_white"),
        build_part(item_name or item.name, item_color, True),
    ]


def _list_known_spells(session: ClientSession) -> list[dict]:
    known_ids = {spell_id.strip().lower() for spell_id in session.known_spell_ids if spell_id.strip()}
    if not known_ids:
        return []

    known_spells = [
        spell
        for spell in load_spells()
        if str(spell.get("spell_id", "")).strip().lower() in known_ids
    ]
    known_spells.sort(key=lambda spell: str(spell.get("name", "")).strip().lower())
    return known_spells


def _resolve_spell_by_name(spell_name: str, spells: list[dict] | None = None) -> tuple[dict | None, str | None]:
    normalized = spell_name.strip().lower()
    if not normalized:
        return None, "Usage: cast 'spell name' [target]"

    def _tokenize(value: str) -> list[str]:
        return [token for token in value.strip().lower().split() if token]

    query_tokens = _tokenize(normalized)
    query_joined = "".join(query_tokens)

    exact_matches: list[dict] = []
    partial_matches: list[dict] = []

    for spell in (spells if spells is not None else load_spells()):
        name = str(spell.get("name", "")).strip()
        spell_normalized = name.lower()
        if not spell_normalized:
            continue

        if spell_normalized == normalized:
            exact_matches.append(spell)
            continue

        name_tokens = _tokenize(spell_normalized)
        initials = "".join(token[0] for token in name_tokens if token)

        token_prefix_match = False
        if query_tokens and len(query_tokens) <= len(name_tokens):
            token_prefix_match = all(
                name_tokens[index].startswith(query_tokens[index])
                for index in range(len(query_tokens))
            )

        joined_prefix_match = bool(query_joined) and initials.startswith(query_joined)
        substring_match = normalized in spell_normalized

        if token_prefix_match or joined_prefix_match or substring_match:
            partial_matches.append(spell)

    if len(exact_matches) == 1:
        return exact_matches[0], None
    if len(exact_matches) > 1:
        names = ", ".join(str(spell.get("name", "Spell")) for spell in exact_matches[:3])
        return None, f"Multiple exact spell matches found: {names}"

    if len(partial_matches) == 1:
        return partial_matches[0], None
    if len(partial_matches) > 1:
        names = ", ".join(str(spell.get("name", "Spell")) for spell in partial_matches[:3])
        return None, f"Multiple spell matches found. Be more specific: {names}"

    return None, f"Unknown spell: {spell_name}"


def _list_known_skills(session: ClientSession) -> list[dict]:
    known_ids = {skill_id.strip().lower() for skill_id in session.known_skill_ids if skill_id.strip()}
    if not known_ids:
        return []

    known_skills = [
        skill
        for skill in load_skills()
        if str(skill.get("skill_id", "")).strip().lower() in known_ids
    ]
    known_skills.sort(key=lambda skill: str(skill.get("name", "")).strip().lower())
    return known_skills


def _resolve_skill_by_name(skill_name: str, skills: list[dict] | None = None) -> tuple[dict | None, str | None]:
    normalized = skill_name.strip().lower()
    if not normalized:
        return None, "Usage: <skill> [target]"

    def _tokenize(value: str) -> list[str]:
        return [token for token in value.strip().lower().split() if token]

    query_tokens = _tokenize(normalized)
    query_joined = "".join(query_tokens)

    exact_matches: list[dict] = []
    partial_matches: list[dict] = []

    for skill in (skills if skills is not None else load_skills()):
        name = str(skill.get("name", "")).strip()
        skill_normalized = name.lower()
        if not skill_normalized:
            continue

        if skill_normalized == normalized:
            exact_matches.append(skill)
            continue

        name_tokens = _tokenize(skill_normalized)
        initials = "".join(token[0] for token in name_tokens if token)

        token_prefix_match = False
        if query_tokens and len(query_tokens) <= len(name_tokens):
            token_prefix_match = all(
                name_tokens[index].startswith(query_tokens[index])
                for index in range(len(query_tokens))
            )

        joined_prefix_match = bool(query_joined) and initials.startswith(query_joined)

        if token_prefix_match or joined_prefix_match:
            partial_matches.append(skill)

    if len(exact_matches) == 1:
        return exact_matches[0], None
    if len(exact_matches) > 1:
        names = ", ".join(str(skill.get("name", "Skill")) for skill in exact_matches[:3])
        return None, f"Multiple exact skill matches found: {names}"

    if len(partial_matches) == 1:
        return partial_matches[0], None
    if len(partial_matches) > 1:
        names = ", ".join(str(skill.get("name", "Skill")) for skill in partial_matches[:3])
        return None, f"Multiple skill matches found. Be more specific: {names}"

    return None, f"Unknown skill: {skill_name}"


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
