from combat import (
    begin_attack,
    COMBAT_ROUND_INTERVAL_SECONDS,
    cast_spell,
    disengage,
    end_combat,
    get_engaged_entity,
    maybe_auto_engage_current_room,
    resolve_corpse_item_selector,
    resolve_combat_round,
    resolve_room_corpse_selector,
    spawn_dummy,
)
from assets import load_spells
from equipment import HAND_MAIN, HAND_OFF, equip_item, remove_item, resolve_equipment_selector, wear_item
import random
import re

from display import (
    build_part,
    display_command_result,
    display_equipment,
    display_error,
    display_force_prompt,
    display_hello,
    display_inventory,
    display_pong,
    display_prompt,
    display_room,
    display_whoami,
)
from models import ClientSession
from sessions import apply_lag, enqueue_command, is_session_lagged
from world import get_room

OutboundMessage = dict[str, object]
OutboundResult = OutboundMessage | list[OutboundMessage]
FLEE_SUCCESS_CHANCE = 0.5

DIRECTION_ALIASES = {
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
    "u": "up",
    "d": "down"
}


def parse_command(command_text: str) -> tuple[str, list[str]]:
    normalized = command_text.strip()
    if not normalized:
        return "", []

    parts = normalized.split()
    verb = parts[0].lower()
    args = parts[1:]
    return verb, args


def normalize_direction(direction: str) -> str:
    direction = direction.lower().strip()
    return DIRECTION_ALIASES.get(direction, direction)


def build_auto_aggro_outbound(session: ClientSession, room_display: OutboundMessage) -> OutboundResult:
    auto_entity = maybe_auto_engage_current_room(session)
    if auto_entity is None:
        return room_display

    payload = room_display.get("payload") if isinstance(room_display, dict) else None
    if isinstance(payload, dict):
        parts = payload.get("parts")
        if isinstance(parts, list):
            parts.extend([
                build_part("\n"),
                build_part("\n"),
                build_part(auto_entity.name),
                build_part(" notices you and attacks!", "bright_white"),
            ])

    combat_result = resolve_combat_round(session)
    if combat_result is None:
        return room_display

    return [room_display, combat_result, display_force_prompt(session)]


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
    room_display["payload"]["parts"] = [
        build_part("You flee ", "bright_white"),
        build_part(flee_direction, "bright_yellow", True),
        build_part(".", "bright_white"),
        build_part("\n"),
        build_part("\n"),
    ] + room_display["payload"]["parts"]

    return build_auto_aggro_outbound(session, room_display)



def try_move(session: ClientSession, direction: str) -> OutboundResult:
    if session.combat.engaged_entity_id is not None:
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


def try_adjust_stat(
    session: ClientSession,
    args: list[str],
    attribute_name: str,
    label: str,
    allow_negative: bool = False
) -> OutboundResult:
    if not args:
        return display_error(f"Usage: {label.lower()} <amount>", session)

    try:
        amount = int(args[0])
    except ValueError:
        return display_error(f"{label} amount must be an integer.", session)

    if not allow_negative and amount < 0:
        return display_error(f"{label} amount must be zero or greater.", session)

    current_value = getattr(session.status, attribute_name)
    new_value = current_value + amount
    if new_value < 0:
        new_value = 0
    setattr(session.status, attribute_name, new_value)

    sign = "+" if amount >= 0 else ""
    return display_command_result(session, [
        build_part(f"{label}: ", "bright_white"),
        build_part(str(current_value), "bright_yellow", True),
        build_part(" -> ", "bright_white"),
        build_part(str(new_value), "bright_green", True),
        build_part(" (", "bright_white"),
        build_part(f"{sign}{amount}", "bright_cyan", True),
        build_part(")", "bright_white"),
    ])


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


def _build_corpse_label(source_name: str) -> str:
    return f"{source_name} corpse"


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

    misc_items = list(session.inventory_items.values())
    misc_items.sort(key=lambda item: item.name.lower())

    matches = []
    for item in misc_items:
        keywords = {token for token in re.findall(r"[a-zA-Z0-9]+", item.name.lower()) if token}
        if all(keyword in keywords for keyword in parts):
            matches.append(item)

    if not matches:
        return None, f"No inventory item matches '{selector}'."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} match(es) found for '{selector}'."
        return matches[requested_index - 1], None

    return matches[0], None


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

    return [
        spell
        for spell in load_spells()
        if str(spell.get("spell_id", "")).strip().lower() in known_ids
    ]


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

        if session.combat.engaged_entity_id is not None:
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
            for index, loot_item in enumerate(loot_items, start=1):
                parts.extend([
                    build_part("\n"),
                    build_part(f" - {index}. ", "bright_white"),
                    build_part(loot_item.name, "bright_magenta", True),
                ])
        else:
            parts.extend([
                build_part("\n"),
                build_part("No lootable items remain.", "bright_white"),
            ])

        return display_command_result(session, parts)

    if verb == "get":
        if len(args) < 2:
            return display_error("Usage: get <item|all|coins> <corpse selector>", session)

        corpse_selector = args[-1].strip()
        if "corpse" not in corpse_selector.lower():
            return display_error("Usage: get <item|all|coins> <corpse selector>", session)

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
                    build_part(item.name, "bright_magenta", True),
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
            build_part(item.name, "bright_magenta", True),
            build_part(" from ", "bright_white"),
            build_part(_build_corpse_label(corpse.source_name), "bright_yellow", True),
            build_part(".", "bright_white"),
        ])

    if verb in {"equipment", "eq", "equi", "eqp"}:
        return display_equipment(session)

    if verb in {"inventory", "inv", "i"}:
        return display_inventory(session)

    if verb in {"spell", "spells"}:
        spells = _list_known_spells(session)
        if not spells:
            return display_command_result(session, [
                build_part("You do not know any spells.", "bright_white"),
            ])

        parts = [
            build_part("Spells", "bright_white", True),
        ]
        for spell in spells:
            spell_name = str(spell.get("name", "Spell"))
            spell_type = str(spell.get("spell_type", "damage")).strip().lower() or "damage"
            cast_type = str(spell.get("cast_type", "target")).strip().lower() or "target"
            dice_count = int(spell.get("damage_dice_count", 0))
            dice_sides = int(spell.get("damage_dice_sides", 0))
            damage_modifier = int(spell.get("damage_modifier", 0))
            support_effect = str(spell.get("support_effect", "")).strip().lower()
            support_amount = int(spell.get("support_amount", 0))
            duration_hours = int(spell.get("duration_hours", 0))
            duration_rounds = int(spell.get("duration_rounds", 0))
            support_mode = str(spell.get("support_mode", "timed")).strip().lower() or "timed"
            description = str(spell.get("description", "")).strip()

            parts.extend([
                build_part("\n"),
                build_part(" - ", "bright_white"),
                build_part(spell_name, "bright_cyan", True),
                build_part(" | cast: ", "bright_white"),
                build_part(cast_type, "bright_yellow", True),
            ])

            if spell_type == "support":
                parts.extend([
                    build_part(" | support: ", "bright_white"),
                    build_part(f"{support_effect}+{support_amount}", "bright_yellow", True),
                ])
                if support_mode == "timed":
                    parts.extend([
                        build_part(" | duration: ", "bright_white"),
                        build_part(f"{duration_hours}h", "bright_yellow", True),
                    ])
                elif support_mode == "battle_rounds":
                    parts.extend([
                        build_part(" | duration: ", "bright_white"),
                        build_part(f"{duration_rounds} rounds", "bright_yellow", True),
                    ])
                else:
                    parts.extend([
                        build_part(" | duration: ", "bright_white"),
                        build_part("instant", "bright_yellow", True),
                    ])
            else:
                parts.extend([
                    build_part(" | dmg: ", "bright_white"),
                    build_part(f"{dice_count}d{dice_sides}+{damage_modifier}", "bright_yellow", True),
                ])

            if description:
                parts.extend([
                    build_part(" | ", "bright_white"),
                    build_part(description, "bright_white"),
                ])

        return display_command_result(session, parts)

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
            if session.combat.engaged_entity_id is not None:
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
        if resolve_error is not None or item is None:
            return display_error(resolve_error or "Unable to resolve equipment selector.", session)

        equipped, equip_result = equip_item(session, item, hand)
        if not equipped:
            return display_error(equip_result, session)

        hand_label = "main hand" if equip_result == HAND_MAIN else "off hand"
        return display_command_result(session, [
            build_part("You equip ", "bright_white"),
            build_part(item.name, "bright_cyan", True),
            build_part(" in your ", "bright_white"),
            build_part(hand_label, "bright_yellow", True),
            build_part(".", "bright_white"),
        ])

    if verb in {"wield", "wiel", "wie", "wi"}:
        if not args:
            return display_error("Usage: wield <selector>", session)

        selector = "".join(arg.strip().lower() for arg in args if arg.strip())
        item, resolve_error = resolve_equipment_selector(session, selector)
        if resolve_error is not None or item is None:
            return display_error(resolve_error or "Unable to resolve equipment selector.", session)

        equipped, equip_result = equip_item(session, item, HAND_MAIN)
        if not equipped:
            return display_error(equip_result, session)

        return display_command_result(session, [
            build_part("You wield ", "bright_white"),
            build_part(item.name, "bright_cyan", True),
            build_part(".", "bright_white"),
        ])

    if verb in {"hold", "hol", "ho"}:
        if not args:
            return display_error("Usage: hold <selector>", session)

        selector = "".join(arg.strip().lower() for arg in args if arg.strip())
        item, resolve_error = resolve_equipment_selector(session, selector)
        if resolve_error is not None or item is None:
            return display_error(resolve_error or "Unable to resolve equipment selector.", session)

        equipped, equip_result = equip_item(session, item, HAND_OFF)
        if not equipped:
            return display_error(equip_result, session)

        return display_command_result(session, [
            build_part("You hold ", "bright_white"),
            build_part(item.name, "bright_cyan", True),
            build_part(" in your off hand.", "bright_white"),
        ])

    if verb in {"wear", "wea", "we", "puton"}:
        if not args:
            return display_error("Usage: wear <selector>", session)

        selector = "".join(arg.strip().lower() for arg in args if arg.strip())
        item, resolve_error = resolve_equipment_selector(session, selector)
        if resolve_error is not None or item is None:
            return display_error(resolve_error or "Unable to resolve equipment selector.", session)

        worn, wear_result = wear_item(session, item)
        if not worn:
            return display_error(wear_result, session)

        return display_command_result(session, [
            build_part("You wear ", "bright_white"),
            build_part(item.name, "bright_cyan", True),
            build_part(" on your ", "bright_white"),
            build_part(wear_result, "bright_yellow", True),
            build_part(".", "bright_white"),
        ])

    if verb in {"drop", "dro", "dr"}:
        if not args:
            return display_error("Usage: drop <selector>", session)

        selector = "".join(arg.strip().lower() for arg in args if arg.strip())
        if not selector:
            return display_error("Usage: drop <selector>", session)

        item, resolve_error = resolve_equipment_selector(session, selector)
        if item is not None and resolve_error is None:
            remove_item(session, item)
            return display_command_result(session, [
                build_part("You drop ", "bright_white"),
                build_part(item.name, "bright_yellow", True),
                build_part(".", "bright_white"),
            ])

        misc_item, misc_error = _resolve_misc_inventory_selector(session, selector)
        if misc_item is not None:
            session.inventory_items.pop(misc_item.item_id, None)
            return display_command_result(session, [
                build_part("You drop ", "bright_white"),
                build_part(misc_item.name, "bright_yellow", True),
                build_part(".", "bright_white"),
            ])

        return display_error(misc_error or resolve_error or "Unable to resolve inventory selector.", session)

    if verb in {"remove", "rem"}:
        if not args:
            return display_error("Usage: rem <selector>", session)

        selector = "".join(arg.strip().lower() for arg in args if arg.strip())
        item, resolve_error = resolve_equipment_selector(session, selector)
        if resolve_error is not None or item is None:
            return display_error(resolve_error or "Unable to resolve equipment selector.", session)

        remove_item(session, item)
        return display_command_result(session, [
            build_part("You remove ", "bright_white"),
            build_part(item.name, "bright_yellow", True),
            build_part(".", "bright_white"),
        ])

    if verb in {"north", "south", "east", "west", "up", "down", "n", "s", "e", "w", "u", "d"}:
        return try_move(session, verb)

    if verb == "go":
        if not args:
            return display_error("Usage: go <direction>", session)

        return try_move(session, args[0])

    if verb == "wait":
        return display_command_result(session, [
            build_part("You wait.", "bright_white")
        ])

    if verb == "heavy":
        response = display_command_result(session, [
            build_part("You use ", "bright_white"),
            build_part("a heavy skill", "bright_red", True),
            build_part(". Lag applied for ", "bright_white"),
            build_part("3.0", "bright_yellow", True),
            build_part(" seconds.", "bright_white")
        ])
        apply_lag(session, 3.0)
        return response

    if verb == "say":
        spoken_text = " ".join(args).strip()
        if not spoken_text:
            return display_error("Usage: say <text>", session)

        return display_command_result(session, [
            build_part("You say, ", "bright_white"),
            build_part(f'"{spoken_text}"', "bright_magenta", True)
        ])

    if verb == "hurt":
        if not args:
            return display_error("Usage: hurt <amount>", session)
        try:
            amount = int(args[0])
        except ValueError:
            return display_error("Hurt amount must be an integer.", session)
        if amount < 0:
            return display_error("Hurt amount must be zero or greater.", session)
        return try_adjust_stat(session, [str(-amount)], "hit_points", "HP", allow_negative=True)

    if verb == "heal":
        return try_adjust_stat(session, args, "hit_points", "HP")

    if verb == "usevigor":
        if not args:
            return display_error("Usage: usevigor <amount>", session)
        try:
            amount = int(args[0])
        except ValueError:
            return display_error("Vigor amount must be an integer.", session)
        if amount < 0:
            return display_error("Vigor amount must be zero or greater.", session)
        return try_adjust_stat(session, [str(-amount)], "vigor", "Vigor", allow_negative=True)

    if verb == "restorevigor":
        return try_adjust_stat(session, args, "vigor", "Vigor")

    if verb == "gaincoins":
        return try_adjust_stat(session, args, "coins", "Coins")

    if verb == "spendcoins":
        if not args:
            return display_error("Usage: spendcoins <amount>", session)
        try:
            amount = int(args[0])
        except ValueError:
            return display_error("Coins amount must be an integer.", session)
        if amount < 0:
            return display_error("Coins amount must be zero or greater.", session)
        return try_adjust_stat(session, [str(-amount)], "coins", "Coins", allow_negative=True)

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

    if input_text.startswith("/"):
        command_line = input_text[1:].strip()
        verb, args = parse_command(command_line)

        if not verb:
            return display_prompt(session)

        if verb == "hello":
            name = " ".join(args).strip() or "unknown"
            return display_hello(name, session)

        if verb == "ping":
            return display_pong(session)

        if verb == "whoami":
            return display_whoami(session)

        return display_error(f"Unknown slash command: /{verb}", session)

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
