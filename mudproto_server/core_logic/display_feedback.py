import asyncio
import re

from attribute_config import player_class_uses_mana
from combat_state import get_engaged_entity, get_entity_condition, get_health_condition
from experience import get_xp_to_next_level
from models import ClientSession
from player_resources import get_player_resource_caps
from session_timing import is_session_lagged
from settings import DIRECTION_ALIASES, DIRECTION_SHORT_LABELS, DIRECTION_SORT_ORDER
from targeting_entities import list_room_entities
from targeting_follow import _find_session_by_identity_key
from world import get_room

from display_core import build_display, build_display_lines, build_part, parts_to_lines, with_leading_blank_lines, with_prompt_gap
from room_exits import format_prompt_exit_token


PROMPT_GAP_LINES = 1


def _get_tick_seconds_remaining(session: ClientSession) -> int | None:
    if session.next_game_tick_monotonic is None:
        return None

    try:
        now = asyncio.get_running_loop().time()
    except RuntimeError:
        return None

    return max(0, int(session.next_game_tick_monotonic - now))


def _direction_short_label(direction: str) -> str:
    normalized = str(direction).strip().lower()
    return DIRECTION_SHORT_LABELS.get(normalized, normalized[:1].upper() or "?")


def _direction_sort_key(direction: str) -> tuple[int, str]:
    normalized = str(direction).strip().lower()
    return DIRECTION_SORT_ORDER.get(normalized, 99), normalized


def build_prompt_parts(session: ClientSession) -> list[dict]:
    if not session.is_authenticated:
        return [build_part("> ", "bright_white")]

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


def resolve_prompt_default(session: ClientSession, prompt_after: bool) -> tuple[bool, list[dict] | None]:
    return resolve_prompt(session, prompt_after, prompt_gap_lines=PROMPT_GAP_LINES)


def build_prompt_parts_default(session: ClientSession) -> list[dict]:
    return with_prompt_gap(build_prompt_parts(session), PROMPT_GAP_LINES)


def build_prompt_lines_default(session: ClientSession) -> list[list[dict]]:
    return parts_to_lines(build_prompt_parts_default(session))


def display_prompt(session: ClientSession) -> dict:
    prompt_after, prompt_parts = resolve_prompt(session, True)
    return build_display([], prompt_after=prompt_after, prompt_parts=prompt_parts)


def display_force_prompt(session: ClientSession) -> dict:
    prompt_parts = build_prompt_parts_default(session)
    return build_display(
        [],
        prompt_after=bool(prompt_parts),
        prompt_parts=prompt_parts,
    )


def display_connected(session: ClientSession) -> dict:
    parts = with_leading_blank_lines([build_part("Connection established.", "bright_green", True)])
    return build_display(parts)


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


def _message_contains_all(lowered: str, fragments: tuple[str, ...]) -> bool:
    return all(fragment in lowered for fragment in fragments)


_MERCHANT_LORE_QUOTES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("not sold here",), "I'm sorry, I don't have that item."),
    (("no longer available",), "I'm sorry, I don't have that item."),
    (("out of stock",), "I'm afraid we've sold the last of that for now."),
    (("need ", " coins"), "You'll need a heavier purse for that one."),
    (("doesn't exist in your inventory",), "I can only bargain for what you are actually carrying."),
)

_SIMPLE_LORE_MESSAGES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("unknown command",), "Those words carry no meaning here."),
    (("not enough mana",), "Your inner reserves are too thin for that spell."),
    (("not enough vigor",), "Your body lacks the vigor for that effort just now."),
    (("you are not engaged with anything",), "No foe presently presses you."),
    (("already fighting",), "You are already locked in battle."),
    (("no exact target named",), "No foe by that exact name is here."),
    (("no exact player named",), "No ally by that exact name is here."),
    (("more than one target matches",), "More than one foe matches that name. Be more specific."),
    (("doesn't exist in your inventory",), "You search your belongings, but find nothing of the sort."),
    (("cannot be used",), "That would not serve you in that way."),
    (("cannot be equipped",), "That would not serve you in that way."),
    (("cannot be worn",), "That would not serve you in that way."),
    (("cannot be wielded",), "That would not serve you in that way."),
    (("cannot be held",), "That would not serve you in that way."),
    (("there are no coins on the ground",), "Not a single coin glints at your feet."),
    (("no corpse matching",), "Nothing of that sort can be found here."),
    (("there are no corpses here",), "Nothing of that sort can be found here."),
    (("cannot go",), "The way does not open for you there."),
    (("destination room not found",), "The way does not open for you there."),
    (("current room not found",), "The world around you wavers strangely for a moment."),
)


def _build_merchant_lore_error_parts(lowered: str, merchant_name: str) -> list[dict] | None:
    for fragments, quote in _MERCHANT_LORE_QUOTES:
        if _message_contains_all(lowered, fragments):
            return _merchant_quote_parts(merchant_name, quote)
    return None


def _build_usage_lore_error_parts(cleaned: str, lowered: str) -> list[dict] | None:
    if not lowered.startswith("usage:"):
        return None

    usage_text = cleaned.split(":", 1)[1].strip() if ":" in cleaned else cleaned
    return [
        build_part("You pause, trying to recall the proper form: ", "bright_white"),
        build_part(usage_text, "bright_white", False),
    ]


def _build_missing_target_lore_parts(lowered: str) -> list[dict] | None:
    if "no target named" not in lowered:
        return None

    target_match = re.search(r"no target named '([^']+)' is here", lowered)
    normalized_target = DIRECTION_ALIASES.get(str(target_match.group(1)).strip().lower()) if target_match else None
    if normalized_target == "up":
        return [build_part("You lift your gaze overhead, but nothing there answers your attention.", "bright_white", False)]
    if normalized_target == "down":
        return [build_part("You glance below, but nothing there reveals itself.", "bright_white", False)]
    if normalized_target in {"north", "south", "east", "west"}:
        return [build_part(f"You peer to the {normalized_target}, but nothing there draws your eye.", "bright_white", False)]
    return [build_part("Nothing of note answers that search here.", "bright_white", False)]


def _build_simple_lore_error_parts(lowered: str) -> list[dict] | None:
    for fragments, lore_text in _SIMPLE_LORE_MESSAGES:
        if _message_contains_all(lowered, fragments):
            return [build_part(lore_text, "bright_white", False)]
    return None


def _build_fallback_lore_error_parts(cleaned: str) -> list[dict]:
    fallback_text = cleaned or "Something feels amiss."
    if fallback_text[-1] not in ".!?":
        fallback_text += "."
    return [build_part(fallback_text, "bright_white", False)]


def _build_lore_error_parts(message: str, session: ClientSession | None = None) -> list[dict]:
    cleaned = str(message).strip()
    lowered = cleaned.lower()

    merchant = _find_room_merchant(session)
    if merchant is not None:
        merchant_name = str(getattr(merchant, "name", "Merchant")).strip() or "Merchant"
        merchant_parts = _build_merchant_lore_error_parts(lowered, merchant_name)
        if merchant_parts is not None:
            return merchant_parts

    usage_parts = _build_usage_lore_error_parts(cleaned, lowered)
    if usage_parts is not None:
        return usage_parts

    target_parts = _build_missing_target_lore_parts(lowered)
    if target_parts is not None:
        return target_parts

    simple_parts = _build_simple_lore_error_parts(lowered)
    if simple_parts is not None:
        return simple_parts

    return _build_fallback_lore_error_parts(cleaned)


def display_error(message: str, session: ClientSession | None = None) -> dict:
    prompt_after = False
    prompt_parts: list[dict] | None = None

    if session is not None:
        prompt_after, prompt_parts = resolve_prompt_default(session, True)

    return build_display(
        with_leading_blank_lines(_build_lore_error_parts(message, session)),
        prompt_after=prompt_after,
        prompt_parts=prompt_parts,
        is_error=True,
    )


def display_command_result(
    session: ClientSession,
    parts: list[dict],
    *,
    compact: bool = False,
    prompt_after: bool = True,
) -> dict:
    prompt_after, prompt_parts = resolve_prompt_default(session, prompt_after)
    content_parts = list(parts)
    if not compact:
        content_parts = with_leading_blank_lines(content_parts)
    elif not prompt_after:
        compact_lines = parts_to_lines(content_parts)
        compact_lines.append([])
        return build_display_lines(
            compact_lines,
            prompt_after=prompt_after,
            prompt_parts=prompt_parts,
        )

    return build_display(
        content_parts,
        prompt_after=prompt_after,
        prompt_parts=prompt_parts,
    )


def display_combat_round_result(session: ClientSession, parts: list[dict]) -> dict:
    return build_display_lines([
        [part for part in parts if isinstance(part, dict)],
        [],
    ])
