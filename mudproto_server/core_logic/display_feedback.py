import asyncio
import re

from attribute_config import player_class_uses_mana
from combat_state import get_engaged_entity, get_entity_condition, get_health_condition
from experience import get_xp_to_next_level
from models import ClientSession
from player_resources import get_player_resource_caps
from session_timing import is_session_lagged
from targeting_entities import list_room_entities
from targeting_follow import _find_session_by_identity_key

from display_core import build_display, build_display_lines, build_part, with_leading_blank_lines, with_prompt_gap
from room_exits import format_prompt_exit_token


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

    import world as _world

    get_room = getattr(_world, "get_room")
    room = get_room(session.player.current_room_id)
    exit_letters = ""

    if room is not None and room.exits:
        exit_letters = "".join(
            format_prompt_exit_token(room, direction)
            for direction in room.exits.keys()
            if str(direction).strip()
        )

    if not exit_letters:
        exit_letters = "None"

    status = session.status
    caps = get_player_resource_caps(session)
    me_condition, me_condition_color = get_health_condition(status.hit_points, caps["hit_points"])
    show_mana = player_class_uses_mana(session.player.class_id) and int(caps.get("mana", 0)) > 0

    parts = [
        build_part(f"{status.hit_points}H", me_condition_color, True),
        build_part(f" {status.vigor}V", "bright_white"),
    ]
    if show_mana:
        parts.append(build_part(f" {status.mana}M", "bright_white"))
    parts.append(build_part(f" {status.coins}C", "bright_white"))

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

    engaged_entity = get_engaged_entity(session)
    is_in_combat = bool(session.combat.engaged_entity_ids)

    # Resolve watch target upfront so we know whether watch mode is active.
    watched_session: ClientSession | None = None
    if not is_in_combat and session.watch_player_key.strip():
        _candidate = _find_session_by_identity_key(session.watch_player_key.strip())
        if (
            _candidate is not None
            and _candidate.is_authenticated
            and _candidate.player.current_room_id == session.player.current_room_id
        ):
            watched_session = _candidate

    # [Me: ...] is hidden when watch mode is active; the watched player's block takes its place.
    if watched_session is None:
        parts.extend([
            build_part(" [Me:", "bright_white"),
            build_part(me_condition.title(), me_condition_color, True),
            build_part("]", "bright_white"),
        ])

    if watched_session is not None:
        watched_caps = get_player_resource_caps(watched_session)
        watched_condition, watched_condition_color = get_health_condition(
            watched_session.status.hit_points, watched_caps["hit_points"]
        )
        watched_name = (watched_session.authenticated_character_name or session.watch_player_name or "?").strip()
        parts.extend([
            build_part(" [", "bright_white"),
            build_part(watched_name, "bright_cyan", True),
            build_part(":", "bright_white"),
            build_part(watched_condition.title(), watched_condition_color, True),
            build_part("]", "bright_white"),
        ])
        watched_entity = get_engaged_entity(watched_session)
        if watched_entity is not None:
            watched_entity_condition, watched_entity_condition_color = get_entity_condition(watched_entity)
            parts.extend([
                build_part(" [", "bright_white"),
                build_part(watched_entity.name),
                build_part(":", "bright_white"),
                build_part(watched_entity_condition.title(), watched_entity_condition_color, True),
                build_part("]", "bright_white"),
            ])

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


def should_show_prompt(session: ClientSession) -> bool:
    return not is_session_lagged(session)


def mark_prompt_pending(session: ClientSession) -> None:
    session.prompt_pending_after_lag = True


def resolve_prompt(
    session: ClientSession,
    prompt_after: bool,
    *,
    prompt_gap_lines: int = 0,
) -> tuple[bool, list[dict] | None]:
    if not prompt_after:
        return False, None

    if should_show_prompt(session):
        session.prompt_pending_after_lag = False
        prompt_parts = with_prompt_gap(build_prompt_parts(session), prompt_gap_lines)
        return True, prompt_parts

    mark_prompt_pending(session)
    return False, None


def resolve_prompt_parts(
    session: ClientSession,
    prompt_after: bool,
    *,
    prompt_gap_lines: int = 0,
) -> list[dict] | None:
    _prompt_after, prompt_parts = resolve_prompt(session, prompt_after, prompt_gap_lines=prompt_gap_lines)
    return prompt_parts if _prompt_after else None


def display_prompt(session: ClientSession) -> dict:
    prompt_after, prompt_parts = resolve_prompt(session, True)
    return build_display([], prompt_after=prompt_after, prompt_parts=prompt_parts)


def display_force_prompt(session: ClientSession) -> dict:
    prompt_parts = with_prompt_gap(build_prompt_parts(session), 1)
    return build_display(
        [],
        prompt_after=bool(prompt_parts),
        prompt_parts=prompt_parts,
    )


def display_connected(session: ClientSession) -> dict:
    parts = with_leading_blank_lines([build_part("Connection established.", "bright_green", True)])
    return build_display(parts)


def display_hello(name: str, session: ClientSession) -> dict:
    prompt_parts = resolve_prompt_parts(session, True, prompt_gap_lines=1)
    return build_display(with_leading_blank_lines([
        build_part("Hello, ", "bright_green"),
        build_part(str(name), "bright_white", True),
    ]), prompt_after=bool(prompt_parts), prompt_parts=prompt_parts)


def display_pong(session: ClientSession) -> dict:
    prompt_parts = resolve_prompt_parts(session, True, prompt_gap_lines=1)
    return build_display(with_leading_blank_lines([
        build_part("Ping received.", "bright_cyan"),
    ]), prompt_after=bool(prompt_parts), prompt_parts=prompt_parts)


def display_whoami(session: ClientSession) -> dict:
    prompt_parts = resolve_prompt_parts(session, True, prompt_gap_lines=1)
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

    return build_display(with_leading_blank_lines(parts), prompt_after=bool(prompt_parts), prompt_parts=prompt_parts)


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
    if "no exact target named" in lowered:
        return [build_part("No foe by that exact name is here.", "bright_white", False)]
    if "no exact player named" in lowered:
        return [build_part("No ally by that exact name is here.", "bright_white", False)]
    if "more than one target matches" in lowered:
        return [build_part("More than one foe matches that name. Be more specific.", "bright_white", False)]
    if "no target named" in lowered:
        direction_aliases = {
            "n": "north",
            "north": "north",
            "s": "south",
            "south": "south",
            "e": "east",
            "east": "east",
            "w": "west",
            "west": "west",
            "u": "up",
            "up": "up",
            "d": "down",
            "down": "down",
        }
        target_match = re.search(r"no target named '([^']+)' is here", lowered)
        normalized_target = direction_aliases.get(str(target_match.group(1)).strip().lower()) if target_match else None
        if normalized_target == "up":
            return [build_part("You lift your gaze overhead, but nothing there answers your attention.", "bright_white", False)]
        if normalized_target == "down":
            return [build_part("You glance below, but nothing there reveals itself.", "bright_white", False)]
        if normalized_target in {"north", "south", "east", "west"}:
            return [build_part(f"You peer to the {normalized_target}, but nothing there draws your eye.", "bright_white", False)]
        return [build_part("Nothing of note answers that search here.", "bright_white", False)]
    if "doesn't exist in your inventory" in lowered:
        return [build_part("You search your belongings, but find nothing of the sort.", "bright_white", False)]
    if "cannot be used" in lowered or "cannot be equipped" in lowered or "cannot be worn" in lowered or "cannot be wielded" in lowered or "cannot be held" in lowered:
        return [build_part("That would not serve you in that way.", "bright_white", False)]
    if "there are no coins on the ground" in lowered:
        return [build_part("Not a single coin glints at your feet.", "bright_white", False)]
    if "no corpse matching" in lowered or "there are no corpses here" in lowered:
        return [build_part("Nothing of that sort can be found here.", "bright_white", False)]
    if "cannot go" in lowered or "destination room not found" in lowered:
        return [build_part("The way does not open for you there.", "bright_white", False)]
    if "current room not found" in lowered:
        return [build_part("The world around you wavers strangely for a moment.", "bright_white", False)]

    if not cleaned:
        cleaned = "Something feels amiss."

    if cleaned[-1] not in ".!?":
        cleaned += "."

    return [
        build_part(cleaned, "bright_white", False),
    ]


def display_error(message: str, session: ClientSession | None = None) -> dict:
    prompt_parts: list[dict] | None = None

    if session is not None:
        prompt_parts = resolve_prompt_parts(session, True, prompt_gap_lines=1)

    return build_display(
        with_leading_blank_lines(_build_lore_error_parts(message, session)),
        prompt_after=bool(prompt_parts),
        prompt_parts=prompt_parts,
        is_error=True,
    )


def display_system(message: str) -> dict:
    return build_display(with_leading_blank_lines([
        build_part(message, "bright_cyan"),
    ]))


def display_queue_ack(session: ClientSession, command_text: str) -> dict:
    mark_prompt_pending(session)
    return build_display(with_leading_blank_lines([
        build_part("Queued: ", "bright_yellow", True),
        build_part(f'"{command_text}"', "bright_white"),
    ]))


def display_command_result(
    session: ClientSession,
    parts: list[dict],
    *,
    compact: bool = False,
    prompt_after: bool = True,
) -> dict:
    prompt_parts = resolve_prompt_parts(session, prompt_after, prompt_gap_lines=1)
    content_parts = list(parts)
    if not compact:
        content_parts = with_leading_blank_lines(content_parts)

    return build_display(
        content_parts,
        prompt_after=bool(prompt_parts),
        prompt_parts=prompt_parts,
    )


def display_combat_round_result(session: ClientSession, parts: list[dict]) -> dict:
    return build_display_lines([
        [part for part in parts if isinstance(part, dict)],
        [],
    ])
