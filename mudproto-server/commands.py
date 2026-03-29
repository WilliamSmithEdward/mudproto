from combat import (
    begin_attack,
    COMBAT_ROUND_INTERVAL_SECONDS,
    cast_spell,
    disengage,
    end_combat,
    get_engaged_entity,
    maybe_auto_engage_current_room,
    resolve_combat_round,
    spawn_dummy,
)
from assets import load_spells
from equipment import HAND_MAIN, HAND_OFF, equip_item, remove_item, resolve_equipment_selector
import random
import re

from display import (
    build_part,
    display_command_result,
    display_equipment,
    display_error,
    display_force_prompt,
    display_hello,
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


def _parse_cast_spell_name(command_text: str, args: list[str]) -> tuple[str | None, str | None]:
    quoted_match = re.match(r"^cast\s+(['\"])(.+?)\1\s*$", command_text.strip(), re.IGNORECASE)
    if quoted_match is not None:
        spell_name = quoted_match.group(2).strip()
        if spell_name:
            return spell_name, None

    spell_name = " ".join(args).strip()
    if not spell_name:
        return None, "Usage: cast 'spell name'"

    return spell_name, None


def _find_spell_by_name(spell_name: str) -> dict | None:
    normalized = spell_name.strip().lower()
    for spell in load_spells():
        if str(spell.get("name", "")).strip().lower() == normalized:
            return spell
    return None


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

    if verb in {"equipment", "eq", "equi", "eqp"}:
        return display_equipment(session)

    if verb in {"spell", "spells"}:
        spells = load_spells()
        if not spells:
            return display_command_result(session, [
                build_part("No spells are available.", "bright_white"),
            ])

        parts = [
            build_part("Spells", "bright_white", True),
        ]
        for spell in spells:
            spell_name = str(spell.get("name", "Spell"))
            mana_cost = int(spell.get("mana_cost", 0))
            spell_type = str(spell.get("spell_type", "damage")).strip().lower() or "damage"
            dice_count = int(spell.get("damage_dice_count", 0))
            dice_sides = int(spell.get("damage_dice_sides", 0))
            damage_modifier = int(spell.get("damage_modifier", 0))
            support_effect = str(spell.get("support_effect", "")).strip().lower()
            support_amount = int(spell.get("support_amount", 0))
            description = str(spell.get("description", "")).strip()

            parts.extend([
                build_part("\n"),
                build_part(" - ", "bright_white"),
                build_part(spell_name, "bright_cyan", True),
                build_part(" | cost: ", "bright_white"),
                build_part(f"{mana_cost}M", "bright_yellow", True),
            ])

            if spell_type == "support":
                parts.extend([
                    build_part(" | support: ", "bright_white"),
                    build_part(f"{support_effect}+{support_amount}", "bright_yellow", True),
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

    if verb == "cast":
        spell_name, parse_error = _parse_cast_spell_name(command_text, args)
        if parse_error is not None or spell_name is None:
            return display_error(parse_error or "Usage: cast 'spell name'", session)

        spell = _find_spell_by_name(spell_name)
        if spell is None:
            return display_error(f"Unknown spell: {spell_name}", session)

        response, cast_applied = cast_spell(session, spell)
        if cast_applied:
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
