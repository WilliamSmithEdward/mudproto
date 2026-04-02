import random
import re
import uuid

from attribute_config import get_player_class_by_id, load_attributes, load_player_classes
from assets import get_item_template_by_id, load_item_templates, load_skills, load_spells
from combat import (
    begin_attack,
    cast_spell,
    disengage,
    end_combat,
    get_engaged_entity,
    list_room_corpses,
    maybe_auto_engage_current_room,
    resolve_corpse_item_selector,
    resolve_combat_round,
    resolve_room_corpse_selector,
    spawn_dummy,
    use_skill,
)
from display import (
    build_menu_table_parts,
    build_line,
    build_part,
    parts_to_lines,
    display_command_result,
    display_equipment,
    display_error,
    display_force_prompt,
    display_inventory,
    display_prompt,
    display_room,
)
from equipment import HAND_MAIN, HAND_OFF, equip_item, get_equipped_main_hand, get_equipped_off_hand, list_worn_items, resolve_equipped_selector, resolve_wear_slot_alias, unequip_item, wear_item
from grammar import indefinite_article, with_article
from inventory import is_item_equippable, resolve_equipment_selector
from models import ClientSession, ItemState
from experience import get_xp_to_next_level
from player_resources import clamp_player_resources_to_caps, get_player_resource_caps
from player_state_db import (
    character_exists,
    create_character,
    get_character_by_name,
    load_player_state,
    normalize_character_name,
    save_player_state,
    verify_character_credentials,
)
from settings import (
    COMBAT_ROUND_INTERVAL_SECONDS,
    FLEE_SUCCESS_CHANCE,
)
from sessions import apply_lag, apply_player_class, ensure_player_attributes, enqueue_command, is_session_lagged
from sessions import (
    get_active_character_session,
    hydrate_session_from_active_character,
    register_authenticated_character_session,
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
    return display_command_result(session, [
        build_part("Enter an existing character name (letters only) or type ", "bright_white"),
        build_part("start", "bright_yellow", True),
        build_part(" to create a new character.", "bright_white"),
    ])


def login_prompt(session: ClientSession) -> OutboundMessage:
    """Minimal login prompt (bare "> ") for re-entry after death or other events."""
    return display_prompt(session)


def _build_class_prompt(session: ClientSession) -> OutboundMessage:
    classes = load_player_classes()
    parts: list[dict] = [
        build_part("Choose a class by id or name:", "bright_white"),
    ]
    for player_class in classes:
        parts.extend([
            build_part("\n"),
            build_part(" - ", "bright_white"),
            build_part(str(player_class.get("class_id", "")), "bright_cyan", True),
            build_part(" (", "bright_white"),
            build_part(str(player_class.get("name", "")), "bright_yellow", True),
            build_part(")", "bright_white"),
        ])
    return display_command_result(session, parts)


def _resolve_class_selection(selection: str) -> dict | None:
    normalized = selection.strip().lower()
    if not normalized:
        return None

    by_id = get_player_class_by_id(normalized)
    if by_id is not None:
        return by_id

    for player_class in load_player_classes():
        if str(player_class.get("name", "")).strip().lower() == normalized:
            return player_class

    return None


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


def _complete_login(session: ClientSession, character_record: dict, *, is_new_character: bool) -> OutboundResult:
    character_key = str(character_record.get("character_key", "")).strip()
    character_name = str(character_record.get("character_name", "")).strip()
    class_id = str(character_record.get("class_id", "")).strip()
    login_room_id = str(character_record.get("login_room_id", "")).strip() or "start"

    session.player_state_key = character_key
    session.authenticated_character_name = character_name
    session.login_room_id = login_room_id
    session.pending_character_name = ""
    session.pending_password = ""

    resumed_from_active = hydrate_session_from_active_character(session, character_key)

    loaded_state = False
    if not resumed_from_active:
        loaded_state = load_player_state(session, player_key=character_key)
        if not loaded_state:
            apply_player_class(session, class_id, initialize_progression=True)
        elif class_id:
            session.player.class_id = class_id

        ensure_player_attributes(session)

        # On fresh login (not session resume), always spawn at configured login room.
        session.player.current_room_id = login_room_id
    else:
        ensure_player_attributes(session)

    clamp_player_resources_to_caps(session)

    session.is_authenticated = True
    session.is_connected = True
    session.disconnected_by_server = False
    session.auth_stage = "authenticated"
    register_authenticated_character_session(session)

    if (not resumed_from_active and not loaded_state) or is_new_character:
        save_player_state(session, player_key=character_key)

    login_room = get_room(session.player.current_room_id)
    if login_room is None:
        session.player.current_room_id = "start"
        login_room = get_room("start")

    if login_room is None:
        return display_error("Login room is not configured.", session)

    room_display = display_room(session, login_room)
    payload = room_display.get("payload") if isinstance(room_display, dict) else None
    if isinstance(payload, dict):
        lines = payload.get("lines")
        if isinstance(lines, list):
            greeting = "Character created" if is_new_character else "Welcome back"
            payload["lines"] = [
                build_line(
                    build_part(f"{greeting}, ", "bright_white"),
                    build_part(character_name, "bright_green", True),
                    build_part(".", "bright_white"),
                ),
                [],
            ] + lines

    return build_auto_aggro_outbound(session, room_display)


def _process_auth_input(session: ClientSession, input_text: str) -> OutboundResult:
    lowered = input_text.strip().lower()

    if session.auth_stage == "awaiting_character_or_start":
        if lowered == "start":
            session.auth_stage = "awaiting_new_character_name"
            return display_command_result(session, [
                build_part("Enter a new character name (letters only).", "bright_white"),
            ])

        normalized_name = normalize_character_name(input_text)
        if normalized_name is None:
            return display_error("Character names must contain letters only.", session)

        character_record = get_character_by_name(normalized_name)
        if character_record is None:
            return display_error(f"Character '{normalized_name}' does not exist.", session)

        session.pending_character_name = str(character_record.get("character_name", normalized_name))
        session.auth_stage = "awaiting_existing_password"
        return display_command_result(session, [
            build_part("Character found. Enter your password.", "bright_white"),
        ])

    if session.auth_stage == "awaiting_existing_password":
        if not input_text.strip():
            return display_error("Password cannot be empty.", session)

        character_record = verify_character_credentials(session.pending_character_name, input_text)
        if character_record is None:
            return display_error("Invalid password.", session)

        return _complete_login(session, character_record, is_new_character=False)

    if session.auth_stage == "awaiting_new_character_name":
        normalized_name = normalize_character_name(input_text)
        if normalized_name is None:
            return display_error("Character names must contain letters only.", session)
        if character_exists(normalized_name):
            return display_error(f"Character '{normalized_name}' already exists.", session)

        session.pending_character_name = normalized_name
        session.auth_stage = "awaiting_new_character_password"
        return display_command_result(session, [
            build_part("Enter a password for your character.", "bright_white"),
        ])

    if session.auth_stage == "awaiting_new_character_password":
        if not input_text.strip():
            return display_error("Password cannot be empty.", session)

        session.pending_password = input_text
        session.auth_stage = "awaiting_new_character_class"
        return _build_class_prompt(session)

    if session.auth_stage == "awaiting_new_character_class":
        selected_class = _resolve_class_selection(input_text)
        if selected_class is None:
            return display_error("Unknown class selection.", session)

        created = create_character(
            character_name=session.pending_character_name,
            password=session.pending_password,
            class_id=str(selected_class.get("class_id", "")).strip(),
            login_room_id="start",
        )
        return _complete_login(session, created, is_new_character=True)

    session.auth_stage = "awaiting_character_or_start"
    return initial_auth_prompt(session)


def normalize_direction(direction: str) -> str:
    direction = direction.lower().strip()
    return DIRECTION_ALIASES.get(direction, direction)


def build_auto_aggro_outbound(session: ClientSession, room_display: OutboundMessage) -> OutboundResult:
    maybe_auto_engage_current_room(session)
    return room_display


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

    return build_auto_aggro_outbound(session, room_display)


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
    return build_auto_aggro_outbound(session, room_display)


def _parse_hand_and_selector(args: list[str]) -> tuple[str | None, str | None, str | None]:
    if not args:
        return None, None, "Usage: equip <selector> [main|off]"

    normalized = [arg.strip().lower() for arg in args if arg.strip()]
    hand_aliases = {
        "main": HAND_MAIN,
        "mainhand": HAND_MAIN,
        "main_hand": HAND_MAIN,
        "off": HAND_OFF,
        "offhand": HAND_OFF,
        "off_hand": HAND_OFF,
    }

    hand: str | None = None
    selector_parts: list[str] = []
    for token in normalized:
        mapped_hand = hand_aliases.get(token)
        if mapped_hand is not None:
            hand = mapped_hand
            continue
        selector_parts.append(token)

    selector = "".join(selector_parts).strip()
    if not selector:
        return None, None, "Usage: equip <selector> [main|off]"

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


def _resolve_inventory_selector(session: ClientSession, selector: str):
    normalized = selector.strip().lower()
    if not normalized:
        return None, "Provide an inventory selector."

    parts = [part for part in normalized.split(".") if part]
    if not parts:
        return None, "Provide an inventory selector."

    requested_index: int | None = None
    if parts[0].isdigit():
        requested_index = int(parts[0])
        parts = parts[1:]
        if requested_index <= 0:
            return None, "Selector index must be 1 or greater."

    if not parts:
        return None, "Provide at least one selector keyword after the index."

    inventory_items = list(session.inventory_items.values())
    inventory_items.sort(key=lambda item: item.name.lower())

    matches = []
    for item in inventory_items:
        keywords = {token for token in re.findall(r"[a-zA-Z0-9]+", item.name.lower()) if token}
        if all(keyword in keywords for keyword in parts):
            matches.append(item)

    if not matches:
        return None, f"{selector} doesn't exist in inventory."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} match(es) found for '{selector}'."
        return matches[requested_index - 1], None

    return matches[0], None


def _resolve_misc_inventory_selector(session: ClientSession, selector: str):
    normalized = selector.strip().lower()
    if not normalized:
        return None, "Provide an inventory selector."

    parts = [part for part in normalized.split(".") if part]
    if not parts:
        return None, "Provide an inventory selector."

    requested_index: int | None = None
    if parts[0].isdigit():
        requested_index = int(parts[0])
        parts = parts[1:]
        if requested_index <= 0:
            return None, "Selector index must be 1 or greater."

    if not parts:
        return None, "Provide at least one selector keyword after the index."

    misc_items = [
        item
        for item in session.inventory_items.values()
        if not is_item_equippable(item)
    ]
    misc_items.sort(key=lambda item: item.name.lower())

    matches = []
    for item in misc_items:
        keywords = {token for token in re.findall(r"[a-zA-Z0-9]+", item.name.lower()) if token}
        if all(keyword in keywords for keyword in parts):
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
    normalized = selector.strip().lower()
    if not normalized:
        return [], None, "Provide an item selector."

    parts = [part for part in normalized.split(".") if part]
    if not parts:
        return [], None, "Provide an item selector."

    requested_index: int | None = None
    if parts[0].isdigit():
        requested_index = int(parts[0])
        parts = parts[1:]
        if requested_index <= 0:
            return [], None, "Selector index must be 1 or greater."

    if not parts:
        return [], None, "Provide at least one selector keyword after the index."

    matches = []
    for item in _list_room_ground_items(session, room_id):
        keywords = {token for token in re.findall(r"[a-zA-Z0-9]+", item.name.lower()) if token}
        if all(keyword in keywords for keyword in parts):
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
    observer_action = (
        observer_action
        .replace("[actor_name]", actor_name)
        .replace("[actor_subject]", actor_name)
        .replace("[actor_object]", "them")
        .replace("[actor_possessive]", "their")
    )

    if observer_context:
        observer_context = (
            observer_context
            .replace("[actor_name]", actor_name)
            .replace("[actor_subject]", actor_name)
            .replace("[actor_object]", "them")
            .replace("[actor_possessive]", "their")
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


def _find_spell_by_name(spell_name: str) -> dict | None:
    normalized = spell_name.strip().lower()
    if not normalized:
        return None

    def _tokenize(value: str) -> list[str]:
        return [token for token in value.strip().lower().split() if token]

    query_tokens = _tokenize(normalized)
    query_joined = "".join(query_tokens)

    exact_matches: list[dict] = []
    partial_matches: list[dict] = []

    for spell in load_spells():
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
        return exact_matches[0]
    if len(exact_matches) > 1:
        return None
    if len(partial_matches) == 1:
        return partial_matches[0]
    return None


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
    verb, args = parse_command(command_text)

    if not verb:
        return display_prompt(session)

    if verb == "spawn":
        target_name = " ".join(args).strip().lower()
        if target_name != "dummy":
            return display_error("Usage: spawn dummy", session)

        return spawn_dummy(session)

    if verb in {"attack", "ki", "kil", "kill"}:
        target_name = " ".join(args).strip()
        if not target_name:
            return display_error(f"Usage: {verb} <target>", session)

        if session.combat.engaged_entity_ids:
            return display_error("You're already fighting!", session)

        return begin_attack(session, target_name)

    if verb == "disengage":
        return disengage(session)

    if verb == "flee":
        return flee(session)

    if verb == "look":
        room = get_room(session.player.current_room_id)
        if room is None:
            return display_error(f"Current room not found: {session.player.current_room_id}", session)

        return display_room(session, room)

    if verb in {"ex", "exa", "exam", "exami", "examin", "examine"}:
        selector_text = " ".join(args).strip()
        if not selector_text:
            return display_error("Usage: examine <corpse selector>", session)

        corpse, resolve_error = resolve_room_corpse_selector(
            session,
            session.player.current_room_id,
            selector_text,
        )
        if corpse is None:
            return display_error(resolve_error or f"No corpse matching '{selector_text}' is here.", session)

        parts = [
            build_part("You examine ", "bright_white"),
            build_part(_build_corpse_label(corpse.source_name), "bright_yellow", True),
            build_part(".", "bright_white"),
        ]

        parts.extend([
            build_part("\n"),
            build_part("Coins: ", "bright_white"),
            build_part(str(corpse.coins), "bright_cyan", True),
        ])

        loot_items = list(corpse.loot_items.values())
        loot_items.sort(key=lambda item: item.name.lower())
        if loot_items:
            parts.extend([
                build_part("\n"),
                build_part("Items:", "bright_white", True),
            ])
            for loot_item in loot_items:
                parts.extend([
                    build_part("\n"),
                    build_part(" - ", "bright_white"),
                    build_part(loot_item.name, _item_highlight_color(loot_item), True),
                ])
        else:
            parts.extend([
                build_part("\n"),
                build_part("No lootable items remain.", "bright_white"),
            ])

        return display_command_result(session, parts)

    if verb == "get":
        if len(args) == 1:
            single_selector = args[0].strip()
            normalized_selector = single_selector.lower()

            if normalized_selector.startswith("all.") and len(single_selector) > 4:
                item_selector = single_selector[4:]
                room_id = session.player.current_room_id
                matches, _, selector_error = _resolve_room_ground_matches(session, room_id, item_selector)
                if selector_error is not None:
                    return display_error(selector_error, session)

                for item in matches:
                    _pickup_ground_item(session, room_id, item)

                parts = [
                    build_part("You take all matching items from the room.", "bright_white"),
                ]
                for item in matches:
                    parts.extend([
                        build_part("\n"),
                        build_part("You take ", "bright_white"),
                        *_build_item_reference_parts(item),
                        build_part(".", "bright_white"),
                    ])
                return display_command_result(session, parts)

            if normalized_selector not in {"coin", "coins", "all"}:
                room_id = session.player.current_room_id
                matches, requested_index, selector_error = _resolve_room_ground_matches(session, room_id, single_selector)
                if selector_error is None:
                    selected_item = matches[0] if requested_index is None else (
                        matches[requested_index - 1] if requested_index <= len(matches) else None
                    )
                    if selected_item is None:
                        return display_error(
                            f"Only {len(matches)} match(es) found for '{single_selector}'.",
                            session,
                        )

                    _pickup_ground_item(session, room_id, selected_item)
                    return display_command_result(session, [
                        build_part("You take ", "bright_white"),
                        *_build_item_reference_parts(selected_item),
                        build_part(".", "bright_white"),
                    ])

        if len(args) == 1 and args[0].strip().lower() in {"coin", "coins"}:
            room_id = session.player.current_room_id
            room_coin_pile = max(0, int(session.room_coin_piles.get(room_id, 0)))
            if room_coin_pile <= 0:
                return display_error("There are no coins on the ground.", session)

            session.room_coin_piles[room_id] = 0
            session.status.coins += room_coin_pile
            return display_command_result(session, [
                build_part("You take ", "bright_white"),
                build_part(str(room_coin_pile), "bright_cyan", True),
                build_part(" coins from the room.", "bright_white"),
            ])

        if len(args) == 1 and args[0].strip().lower() == "all":
            corpses = list_room_corpses(session, session.player.current_room_id)
            room_id = session.player.current_room_id
            room_items = _list_room_ground_items(session, room_id)
            room_coin_pile = max(0, int(session.room_coin_piles.get(room_id, 0)))
            if not corpses and room_coin_pile <= 0 and not room_items:
                return display_error("There is nothing to loot in this room.", session)

            total_coins = room_coin_pile
            looted_items = []

            if room_coin_pile > 0:
                session.room_coin_piles[room_id] = 0

            for item in room_items:
                _pickup_ground_item(session, room_id, item)
                looted_items.append(item)

            for corpse in corpses:
                corpse_coins = max(0, corpse.coins)
                total_coins += corpse_coins
                corpse.coins = 0

                corpse_items = list(corpse.loot_items.values())
                corpse_items.sort(key=lambda item: item.name.lower())
                for item in corpse_items:
                    session.inventory_items[item.item_id] = item
                    corpse.loot_items.pop(item.item_id, None)
                    looted_items.append(item)

            if total_coins <= 0 and not looted_items:
                return display_error("There is nothing to loot in this room.", session)

            session.status.coins += total_coins

            parts = [
                build_part("You loot everything in the room.", "bright_white"),
            ]
            if total_coins > 0:
                parts.extend([
                    build_part("\n"),
                    build_part("Coins +", "bright_white"),
                    build_part(str(total_coins), "bright_cyan", True),
                ])
            for item in looted_items:
                parts.extend([
                    build_part("\n"),
                    build_part("You take ", "bright_white"),
                    *_build_item_reference_parts(item),
                    build_part(".", "bright_white"),
                ])

            return display_command_result(session, parts)

        if len(args) < 2:
            return display_error("Usage: get <item|all|coins> <corpse selector>", session)

        corpse_selector = args[-1].strip()

        item_selector = " ".join(args[:-1]).strip()
        if not item_selector:
            return display_error("Usage: get <item|all|coins> <corpse selector>", session)

        corpse, resolve_error = resolve_room_corpse_selector(
            session,
            session.player.current_room_id,
            corpse_selector,
        )
        if corpse is None:
            return display_error(resolve_error or f"No corpse matching '{corpse_selector}' is here.", session)

        normalized_item_selector = item_selector.lower()

        if normalized_item_selector == "all":
            taken_coins = max(0, corpse.coins)
            taken_items = list(corpse.loot_items.values())
            taken_items.sort(key=lambda item: item.name.lower())

            if taken_coins <= 0 and not taken_items:
                return display_error("There is nothing to loot from that corpse.", session)

            corpse.coins = 0
            if taken_coins > 0:
                session.status.coins += taken_coins

            for item in taken_items:
                session.inventory_items[item.item_id] = item
                corpse.loot_items.pop(item.item_id, None)

            parts = [
                build_part("You loot ", "bright_white"),
                build_part(_build_corpse_label(corpse.source_name), "bright_yellow", True),
                build_part(".", "bright_white"),
            ]
            if taken_coins > 0:
                parts.extend([
                    build_part("\n"),
                    build_part("Coins +", "bright_white"),
                    build_part(str(taken_coins), "bright_cyan", True),
                ])
            for item in taken_items:
                parts.extend([
                    build_part("\n"),
                    build_part("You take ", "bright_white"),
                    *_build_item_reference_parts(item),
                    build_part(".", "bright_white"),
                ])

            return display_command_result(session, parts)

        if normalized_item_selector in {"coin", "coins"}:
            if corpse.coins <= 0:
                return display_error("That corpse has no coins left.", session)

            taken_coins = corpse.coins
            corpse.coins = 0
            session.status.coins += taken_coins
            return display_command_result(session, [
                build_part("You take ", "bright_white"),
                build_part(str(taken_coins), "bright_cyan", True),
                build_part(" coins from ", "bright_white"),
                build_part(_build_corpse_label(corpse.source_name), "bright_yellow", True),
                build_part(".", "bright_white"),
            ])

        item, item_error = resolve_corpse_item_selector(corpse, item_selector)
        if item is None:
            return display_error(item_error or f"No item matching '{item_selector}' is on that corpse.", session)

        corpse.loot_items.pop(item.item_id, None)
        session.inventory_items[item.item_id] = item

        return display_command_result(session, [
            build_part("You take ", "bright_white"),
            *_build_item_reference_parts(item),
            build_part(" from ", "bright_white"),
            build_part(_build_corpse_label(corpse.source_name), "bright_yellow", True),
            build_part(".", "bright_white"),
        ])

    if verb in {"equipment", "eq", "equi", "eqp"}:
        return display_equipment(session)

    if verb in {"inventory", "inv", "i"}:
        return display_inventory(session)

    if verb in {"attributes", "attribute", "attr", "attrs", "stats", "stat"}:
        configured_attributes = load_attributes()
        parts = [
            build_part("Attributes", "bright_white", True),
        ]

        for attribute in configured_attributes:
            attribute_id = str(attribute.get("attribute_id", "")).strip().lower()
            name = str(attribute.get("name", attribute_id)).strip() or attribute_id
            value = int(session.player.attributes.get(attribute_id, 0))
            parts.extend([
                build_part("\n"),
                build_part(" - ", "bright_white"),
                build_part(name, "bright_cyan", True),
                build_part(" (", "bright_white"),
                build_part(attribute_id, "bright_yellow", True),
                build_part("): ", "bright_white"),
                build_part(str(value), "bright_green", True),
            ])

        return display_command_result(session, parts)

    if verb in {"score", "scor", "sco", "sc"}:
        return display_score(session)

    if verb in {"spell", "spells", "sp", "spe", "spel"}:
        spells = _list_known_spells(session)
        if not spells:
            return display_command_result(session, [
                build_part("You do not know any spells.", "bright_white"),
            ])

        menu_rows = [
            (
                str(spell.get("name", "Spell")).strip() or "Spell",
                str(spell.get("school", "Unknown")).strip() or "Unknown",
                int(spell.get("mana_cost", 0)),
            )
            for spell in spells
        ]
        return display_command_result(
            session,
            _build_cost_menu_parts("Spells", menu_rows, "Mana", middle_column_header="School"),
        )

    if verb in {"skills", "sk", "ski", "skil", "skill"} and not args:
        skills = _list_known_skills(session)
        if not skills:
            return display_command_result(session, [
                build_part("You do not know any skills.", "bright_white"),
            ])

        menu_rows = [
            (
                str(skill.get("name", "Skill")).strip() or "Skill",
                "",
                int(skill.get("vigor_cost", 0)),
            )
            for skill in skills
        ]
        return display_command_result(session, _build_cost_menu_parts("Skills", menu_rows, "Vigor"))

    if verb in {"cast", "c", "ca", "cas"}:
        spell_name, target_name, parse_error = _parse_cast_spell(command_text, args, verb)
        if parse_error is not None or spell_name is None:
            return display_error(parse_error or "Usage: cast 'spell name' [target]", session)

        known_spells = _list_known_spells(session)
        if not known_spells:
            return display_error("You do not know any spells.", session)

        spell, resolve_error = _resolve_spell_by_name(spell_name, known_spells)
        if spell is None:
            return display_error(resolve_error or f"You do not know spell: {spell_name}", session)

        response, cast_applied = cast_spell(session, spell, target_name)
        if cast_applied:
            if session.combat.engaged_entity_ids:
                session.combat.skip_melee_rounds = max(1, session.combat.skip_melee_rounds)
            try:
                apply_lag(session, COMBAT_ROUND_INTERVAL_SECONDS)
            except RuntimeError:
                pass
        return response

    if verb == "equip":
        if not args:
            return display_equipment(session)

        hand, selector, parse_error = _parse_hand_and_selector(args)
        if parse_error is not None or selector is None:
            return display_error(parse_error or "Usage: equip <selector> [main|off]", session)

        item, resolve_error = resolve_equipment_selector(session, selector)
        if item is None:
            inventory_item, inventory_error = _resolve_inventory_selector(session, selector)
            if inventory_item is not None:
                return display_error(f"{inventory_item.name} cannot be equipped.", session)
            return display_error(resolve_error or "Unable to resolve equipment selector.", session)

        equipped, equip_result = equip_item(session, item, hand)
        if not equipped:
            return display_error(equip_result, session)

        hand_label = "main hand" if equip_result == HAND_MAIN else "off hand"
        return display_command_result(session, [
            build_part("You equip ", "bright_white"),
            *_build_item_reference_parts(item),
            build_part(" in your ", "bright_white"),
            build_part(hand_label, "bright_yellow", True),
            build_part(".", "bright_white"),
        ])

    if verb in {"wield", "wiel", "wie", "wi"}:
        if not args:
            return display_error("Usage: wield <selector>", session)

        selector = ".".join(arg.strip().lower() for arg in args if arg.strip())
        item, resolve_error = resolve_equipment_selector(session, selector)
        if item is None:
            inventory_item, inventory_error = _resolve_inventory_selector(session, selector)
            if inventory_item is None:
                return display_error(resolve_error or inventory_error or "Unable to resolve equipment selector.", session)
            return display_error(f"{inventory_item.name} cannot be wielded.", session)

        current_main = get_equipped_main_hand(session)
        if current_main is not None:
            return display_error(
                f"Your main hand is already occupied by {current_main.name}. Remove it first.",
                session,
            )

        equipped, equip_result = equip_item(session, item, HAND_MAIN)
        if not equipped:
            return display_error(equip_result, session)

        return display_command_result(session, [
            build_part("You wield ", "bright_white"),
            *_build_item_reference_parts(item),
            build_part(".", "bright_white"),
        ])

    if verb in {"hold", "hol", "ho"}:
        if not args:
            return display_error("Usage: hold <selector>", session)

        selector = ".".join(arg.strip().lower() for arg in args if arg.strip())
        item, resolve_error = resolve_equipment_selector(session, selector)
        if item is None:
            inventory_item, inventory_error = _resolve_inventory_selector(session, selector)
            if inventory_item is None:
                return display_error(resolve_error or inventory_error or "Unable to resolve equipment selector.", session)
            return display_error(f"{inventory_item.name} cannot be held.", session)

        current_off = get_equipped_off_hand(session)
        if current_off is not None:
            return display_error(
                f"Your off hand is already occupied by {current_off.name}. Remove it first.",
                session,
            )

        equipped, equip_result = equip_item(session, item, HAND_OFF)
        if not equipped:
            return display_error(equip_result, session)

        return display_command_result(session, [
            build_part("You hold ", "bright_white"),
            *_build_item_reference_parts(item),
            build_part(" in your off hand.", "bright_white"),
        ])

    if verb in {"wear", "wea", "we", "puton"}:
        if not args:
            return display_error("Usage: wear <selector> [location]", session)

        selector, wear_location, parse_error = _parse_wear_selector_and_location(args)
        if parse_error is not None or selector is None:
            return display_error(parse_error or "Usage: wear <selector> [location]", session)

        if selector.startswith("all.") and len(selector) > 4:
            item_selector = selector[4:]
            selector_tokens = {token for token in re.findall(r"[a-zA-Z0-9]+", item_selector) if token}
            if not selector_tokens:
                return display_error("Usage: wear all.<item>", session)

            wearable_items = []

            for inventory_item in list(session.inventory_items.values()):
                item_keywords = {token for token in re.findall(r"[a-zA-Z0-9]+", inventory_item.name.lower()) if token}
                if not selector_tokens.issubset(item_keywords):
                    continue

                if not is_item_equippable(inventory_item) or inventory_item.slot.strip().lower() != "armor":
                    continue
                wearable_items.append(inventory_item)

            wearable_items.sort(key=lambda item: (len(item.wear_slots) if item.wear_slots else 1, item.name.lower(), item.item_id))

            if not wearable_items:
                return display_error(f"No wearable inventory item matches '{item_selector}'.", session)

            worn_results: list[tuple[str, str]] = []
            for item in wearable_items:
                worn, wear_result = wear_item(session, item)
                if worn:
                    worn_results.append((item.name, wear_result))

            if not worn_results:
                return display_error("You cannot wear any additional matching items right now.", session)

            parts = [
                build_part("You wear all matching items.", "bright_white"),
            ]
            for item_name, slot_name in worn_results:
                parts.extend([
                    build_part("\n"),
                    build_part(" - ", "bright_white"),
                    build_part(item_name, "bright_cyan", True),
                    build_part(" on your ", "bright_white"),
                    build_part(slot_name, "bright_yellow", True),
                    build_part(".", "bright_white"),
                ])

            return display_command_result(session, parts)

        if selector == "all":
            wearable_items = []
            for inventory_item in list(session.inventory_items.values()):
                if is_item_equippable(inventory_item) and inventory_item.slot.strip().lower() == "armor":
                    wearable_items.append(inventory_item)

            wearable_items.sort(key=lambda item: (len(item.wear_slots) if item.wear_slots else 1, item.name.lower(), item.item_id))

            if not wearable_items:
                return display_error("You have nothing wearable in your inventory.", session)

            worn_results: list[tuple[str, str]] = []
            for item in wearable_items:
                worn, wear_result = wear_item(session, item)
                if worn:
                    worn_results.append((item.name, wear_result))

            if not worn_results:
                return display_error("You cannot wear any additional items right now.", session)

            parts = [
                build_part("You wear everything you can.", "bright_white"),
            ]
            for item_name, slot_name in worn_results:
                parts.extend([
                    build_part("\n"),
                    build_part(" - ", "bright_white"),
                    build_part(item_name, "bright_cyan", True),
                    build_part(" on your ", "bright_white"),
                    build_part(slot_name, "bright_yellow", True),
                    build_part(".", "bright_white"),
                ])

            return display_command_result(session, parts)

        item, resolve_error = _resolve_wear_inventory_selector(session, selector)
        if resolve_error is not None or item is None:
            return display_error(resolve_error or "Unable to resolve inventory selector.", session)

        if item.slot.strip().lower() != "armor":
            return display_error(f"{item.name} cannot be worn.", session)

        worn, wear_result = wear_item(session, item, wear_location)
        if not worn:
            return display_error(wear_result, session)

        return display_command_result(session, [
            build_part("You wear ", "bright_white"),
            *_build_item_reference_parts(item),
            build_part(" on your ", "bright_white"),
            build_part(wear_result, "bright_yellow", True),
            build_part(".", "bright_white"),
        ])

    if verb in {"drop", "dro", "dr"}:
        if not args:
            return display_error("Usage: drop <selector>", session)

        selector = ".".join(arg.strip().lower() for arg in args if arg.strip())
        if not selector:
            return display_error("Usage: drop <selector>", session)

        if selector.startswith("all.") and len(selector) > 4:
            item_selector = selector[4:]
            selector_tokens = {token for token in re.findall(r"[a-zA-Z0-9]+", item_selector) if token}
            if not selector_tokens:
                return display_error("Usage: drop all.<item>", session)

            inventory_matches = []
            for item in list(session.inventory_items.values()):
                item_keywords = {token for token in re.findall(r"[a-zA-Z0-9]+", item.name.lower()) if token}
                if selector_tokens.issubset(item_keywords):
                    inventory_matches.append(item)

            if not inventory_matches:
                return display_error(f"No inventory item matches '{item_selector}'.", session)

            dropped_items = []

            for item in inventory_matches:
                session.inventory_items.pop(item.item_id, None)
                _add_item_to_room_ground(session, session.player.current_room_id, item)
                dropped_items.append(item)

            parts = [
                build_part("You drop all matching items.", "bright_white"),
            ]
            for item in dropped_items:
                parts.extend([
                    build_part("\n"),
                    build_part(" - ", "bright_white"),
                    build_part(item.name, _item_highlight_color(item), True),
                ])
            return display_command_result(session, parts)

        coin_drop_match = re.match(r"^(\d+)\*coins?$", selector)
        if coin_drop_match is not None:
            drop_amount = int(coin_drop_match.group(1))
            if drop_amount <= 0:
                return display_error("Coin drop amount must be greater than zero.", session)
            if session.status.coins < drop_amount:
                return display_error(
                    f"You only have {session.status.coins} coins.",
                    session,
                )

            session.status.coins -= drop_amount
            room_id = session.player.current_room_id
            existing_pile = max(0, int(session.room_coin_piles.get(room_id, 0)))
            session.room_coin_piles[room_id] = existing_pile + drop_amount
            return display_command_result(session, [
                build_part("You drop ", "bright_white"),
                build_part(str(drop_amount), "bright_cyan", True),
                build_part(" coins into a pile on the ground.", "bright_white"),
            ])

        if selector == "all":
            inventory_items = list(session.inventory_items.values())

            if not inventory_items:
                return display_error("You have nothing to drop.", session)

            dropped_count = 0
            for item in inventory_items:
                session.inventory_items.pop(item.item_id, None)
                _add_item_to_room_ground(session, session.player.current_room_id, item)
                dropped_count += 1

            return display_command_result(session, [
                build_part("You drop all carried items.", "bright_white"),
                build_part("\n"),
                build_part("Items dropped: ", "bright_white"),
                build_part(str(dropped_count), "bright_yellow", True),
            ])

        inventory_item, inventory_error = _resolve_inventory_selector(session, selector)
        if inventory_item is not None:
            session.inventory_items.pop(inventory_item.item_id, None)
            _add_item_to_room_ground(session, session.player.current_room_id, inventory_item)
            return display_command_result(session, [
                build_part("You drop ", "bright_white"),
                *_build_item_reference_parts(inventory_item),
                build_part(".", "bright_white"),
            ])

        return display_error(inventory_error or "Unable to resolve inventory selector.", session)

    if verb in {"remove", "rem"}:
        if not args:
            return display_error("Usage: rem <selector>", session)

        selector = ".".join(arg.strip().lower() for arg in args if arg.strip())
        if selector.startswith("all.") and len(selector) > 4:
            item_selector = selector[4:]
            selector_tokens = {token for token in re.findall(r"[a-zA-Z0-9]+", item_selector) if token}
            if not selector_tokens:
                return display_error("Usage: rem all.<item>", session)

            worn_items = list_worn_items(session)
            matches = []
            seen_item_ids: set[str] = set()
            for _, worn_item in worn_items:
                if worn_item.item_id in seen_item_ids:
                    continue
                item_keywords = {token for token in re.findall(r"[a-zA-Z0-9]+", worn_item.name.lower()) if token}
                if selector_tokens.issubset(item_keywords):
                    matches.append(worn_item)
                seen_item_ids.add(worn_item.item_id)

            if not matches:
                return display_error(f"No equipped item matches '{item_selector}'.", session)

            removed_items = []
            for worn_item in matches:
                if unequip_item(session, worn_item):
                    removed_items.append(worn_item)

            if not removed_items:
                return display_error(f"No equipped item matches '{item_selector}'.", session)

            parts = [
                build_part("You remove all matching equipped items.", "bright_white"),
            ]
            for item in removed_items:
                parts.extend([
                    build_part("\n"),
                    build_part(" - ", "bright_white"),
                    build_part(item.name, _item_highlight_color(item), True),
                ])
            return display_command_result(session, parts)

        if selector == "all":
            worn_items = list_worn_items(session)
            if not worn_items:
                return display_error("You have nothing to remove.", session)

            removed_items = []
            seen_item_ids: set[str] = set()
            for _, worn_item in worn_items:
                if worn_item.item_id in seen_item_ids:
                    continue
                if unequip_item(session, worn_item):
                    removed_items.append(worn_item)
                seen_item_ids.add(worn_item.item_id)

            if not removed_items:
                return display_error("You have nothing to remove.", session)

            parts = [
                build_part("You remove all equipped items and place them in your inventory.", "bright_white"),
            ]
            for item in removed_items:
                parts.extend([
                    build_part("\n"),
                    build_part(" - ", "bright_white"),
                    build_part(item.name, _item_highlight_color(item), True),
                ])
            return display_command_result(session, parts)

        item, resolve_error = resolve_equipped_selector(session, selector)
        if resolve_error is not None or item is None:
            return display_error(resolve_error or "Unable to resolve equipped item selector.", session)

        was_equipped = unequip_item(session, item)
        if not was_equipped:
            return display_error(f"{item.name} is not currently worn or held.", session)

        return display_command_result(session, [
            build_part("You remove ", "bright_white"),
            build_part(item.name, _item_highlight_color(item), True),
            build_part(" and place it in your inventory.", "bright_white"),
        ])

    if normalize_direction(verb) in {"north", "south", "east", "west", "up", "down"}:
        return try_move(session, verb)

    if verb == "use":
        selector = ".".join(arg.strip().lower() for arg in args if arg.strip())
        return _use_misc_item(session, selector)

    if verb == "say":
        spoken_text = " ".join(args).strip()
        if not spoken_text:
            return display_error("Usage: say <text>", session)

        return display_command_result(session, [
            build_part("You say, ", "bright_white"),
            build_part(f'"{spoken_text}"', "bright_magenta", True)
        ])


    # Try to resolve unknown verb as direct skill invocation (e.g., 'jab scout').
    # Lowest precedence — only runs after all other commands have failed to match.
    known_skills = _list_known_skills(session)
    if verb not in {"skill", "sk", "ski", "skil", "skl", "skills", "use"} and known_skills:
        for cut in range(len(args) + 1, 0, -1):
            candidate_verb_args = [verb] + args[:cut-1]
            candidate_skill_name = " ".join(candidate_verb_args).strip()
            candidate_target_name = " ".join(args[cut-1:]).strip() or None
            candidate_skill, _ = _resolve_skill_by_name(candidate_skill_name, known_skills)
            if candidate_skill is not None:
                verb = "skill"
                args = candidate_verb_args + (args[cut-1:] if args[cut-1:] else [])
                break

    if verb in {"skill", "sk", "ski", "skil", "skl"}:
        if not known_skills:
            return display_error("You do not know any skills.", session)

        skill_name, target_name, parse_error = _parse_skill_use(args)
        if parse_error is not None or skill_name is None:
            return display_error(parse_error or "Usage: <skill> [target]", session)

        # Resolve by trying longest-to-shortest splits so
        # `jab scout` maps to skill `jab` with target `scout`.
        if target_name is None and len(args) > 1:
            for cut in range(len(args), 0, -1):
                candidate_skill_name = " ".join(args[:cut]).strip()
                candidate_target_name = " ".join(args[cut:]).strip() or None
                candidate_skill, _ = _resolve_skill_by_name(candidate_skill_name, known_skills)
                if candidate_skill is not None:
                    skill_name = candidate_skill_name
                    target_name = candidate_target_name
                    break

        skill, resolve_error = _resolve_skill_by_name(skill_name, known_skills)
        if skill is None:
            return display_error(resolve_error or f"Unknown skill: {skill_name}", session)

        response, skill_applied = use_skill(session, skill, target_name)
        if skill_applied and session.combat.engaged_entity_ids:
            lag_rounds = max(0, int(skill.get("lag_rounds", 0)))
            if lag_rounds > 0:
                try:
                    apply_lag(session, lag_rounds * COMBAT_ROUND_INTERVAL_SECONDS)
                except RuntimeError:
                    pass
        return response

    return display_error(f"Unknown command: {verb}", session)


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
        return _process_auth_input(session, input_text)

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
