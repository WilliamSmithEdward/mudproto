import asyncio

from command_handlers.types import ErrorCode, ErrorContext
from attribute_config import player_class_uses_mana
from combat_state import get_engaged_entity, get_entity_condition, get_health_condition
from experience import get_xp_to_next_level
from models import ClientSession
from player_resources import get_player_resource_caps
from session_timing import is_session_lagged
from settings import (
    DIRECTION_ALIASES,
    DIRECTION_SHORT_LABELS,
    DIRECTION_SORT_ORDER,
    DISPLAY_FEEDBACK_MERCHANT_QUOTES,
    DISPLAY_FEEDBACK_SIMPLE_MESSAGES,
)
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
        return [build_part("> ", "display_feedback.prompt.guest")]

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
        build_part(f" {status.vigor}V", "display_feedback.prompt.vitals"),
    ]
    if show_mana:
        parts.append(build_part(f" {status.mana}M", "display_feedback.prompt.vitals"))
    parts.append(build_part(f" {status.coins}C", "display_feedback.prompt.vitals"))

    xp_to_next_level = get_xp_to_next_level(session.player.experience_points)
    parts.extend([
        build_part(f" {xp_to_next_level}X", "display_feedback.prompt.vitals"),
    ])

    tick_seconds_remaining = _get_tick_seconds_remaining(session)
    if tick_seconds_remaining is not None:
        parts.extend([
            build_part(" [Tick:", "display_feedback.prompt.bracket"),
            build_part(f"{tick_seconds_remaining}s", "display_feedback.prompt.tick_value", True),
            build_part("]", "display_feedback.prompt.bracket"),
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
            build_part(" [Me:", "display_feedback.prompt.bracket"),
            build_part(me_condition.title(), me_condition_color, True),
            build_part("]", "display_feedback.prompt.bracket"),
        ])

    if watched_session is not None:
        watched_caps = get_player_resource_caps(watched_session)
        watched_condition, watched_condition_color = get_health_condition(
            watched_session.status.hit_points, watched_caps["hit_points"]
        )
        watched_name = (watched_session.authenticated_character_name or session.watch_player_name or "?").strip()
        parts.extend([
            build_part(" [", "display_feedback.prompt.bracket"),
            build_part(watched_name, "display_feedback.prompt.watch_name", True),
            build_part(":", "display_feedback.prompt.bracket"),
            build_part(watched_condition.title(), watched_condition_color, True),
            build_part("]", "display_feedback.prompt.bracket"),
        ])
        watched_entity = get_engaged_entity(watched_session)
        if watched_entity is not None:
            watched_entity_condition, watched_entity_condition_color = get_entity_condition(watched_entity)
            parts.extend([
                build_part(" [", "display_feedback.prompt.bracket"),
                build_part(watched_entity.name),
                build_part(":", "display_feedback.prompt.bracket"),
                build_part(watched_entity_condition.title(), watched_entity_condition_color, True),
                build_part("]", "display_feedback.prompt.bracket"),
            ])

    if engaged_entity is not None:
        npc_condition, npc_condition_color = get_entity_condition(engaged_entity)
        parts.extend([
            build_part(" [", "display_feedback.prompt.bracket"),
            build_part(engaged_entity.name),
            build_part(":", "display_feedback.prompt.bracket"),
            build_part(npc_condition.title(), npc_condition_color, True),
            build_part("]", "display_feedback.prompt.bracket"),
        ])

    parts.append(build_part(f" Exits:{exit_letters}> ", "display_feedback.prompt.exits"))
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
    parts = with_leading_blank_lines([build_part("Connection established.", "display_feedback.connected", True)])
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
        build_part(merchant_name, "display_feedback.merchant.name", False),
        build_part(' says, "', "display_feedback.merchant.quote"),
        build_part(quote, "display_feedback.merchant.quote", False),
        build_part('"', "display_feedback.merchant.quote"),
    ]





def _build_usage_lore_error_parts(usage_text: str) -> list[dict]:
    cleaned_usage = str(usage_text).strip() or "that command"
    return [
        build_part("You pause, trying to recall the proper form: ", "display_feedback.usage.text"),
        build_part(cleaned_usage, "display_feedback.usage.text", False),
    ]


def _build_missing_target_lore_parts(target_name: str | None = None) -> list[dict]:
    normalized_target_name = str(target_name or "").strip().lower()
    normalized_target = DIRECTION_ALIASES.get(normalized_target_name)
    if normalized_target == "up":
        return [build_part("You lift your gaze overhead, but nothing there answers your attention.", "display_feedback.missing_target.text", False)]
    if normalized_target == "down":
        return [build_part("You glance below, but nothing there reveals itself.", "display_feedback.missing_target.text", False)]
    if normalized_target in {"north", "south", "east", "west"}:
        return [build_part(f"You peer to the {normalized_target}, but nothing there draws your eye.", "display_feedback.missing_target.text", False)]
    return [build_part("Nothing of note answers that search here.", "display_feedback.missing_target.text", False)]


def _build_raw_error_parts(cleaned: str) -> list[dict]:
    fallback_text = cleaned or "Something feels amiss."
    if fallback_text[-1] not in ".!?":
        fallback_text += "."
    return [build_part(fallback_text, "display_feedback.error.text", False)]


def _build_coded_lore_error_parts(
    error_code: ErrorCode,
    session: ClientSession | None = None,
    error_context: ErrorContext | None = None,
) -> list[dict] | None:
    normalized_code = str(error_code).strip().lower()
    context = error_context or {}

    if normalized_code == "usage":
        usage_text = str(context.get("usage", "")).strip()
        if usage_text:
            return _build_usage_lore_error_parts(usage_text)
        return None

    if normalized_code == "target-not-found":
        target_name = str(context.get("target", "")).strip()
        return _build_missing_target_lore_parts(target_name or None)

    if normalized_code == "corpse-not-found":
        return [build_part("Nothing of that sort can be found here.", "display_feedback.error.text", False)]

    if normalized_code in DISPLAY_FEEDBACK_SIMPLE_MESSAGES:
        return [build_part(DISPLAY_FEEDBACK_SIMPLE_MESSAGES[normalized_code], "display_feedback.error.text", False)]

    if normalized_code == "no-merchant-here":
        return [build_part(DISPLAY_FEEDBACK_MERCHANT_QUOTES[normalized_code], "display_feedback.error.text", False)]

    merchant = _find_room_merchant(session)
    if merchant is not None and normalized_code in DISPLAY_FEEDBACK_MERCHANT_QUOTES:
        merchant_name = str(getattr(merchant, "name", "Merchant")).strip() or "Merchant"
        return _merchant_quote_parts(merchant_name, DISPLAY_FEEDBACK_MERCHANT_QUOTES[normalized_code])

    return None


def _build_lore_error_parts(
    message: str,
    session: ClientSession | None = None,
    *,
    error_code: ErrorCode | None = None,
    error_context: ErrorContext | None = None,
) -> list[dict]:
    cleaned = str(message).strip()

    if error_code is not None:
        coded_parts = _build_coded_lore_error_parts(error_code, session, error_context)
        if coded_parts is not None:
            return coded_parts

    return _build_raw_error_parts(cleaned)


def display_error(
    message: str,
    session: ClientSession | None = None,
    *,
    error_code: ErrorCode | None = None,
    error_context: ErrorContext | None = None,
) -> dict:
    prompt_after = False
    prompt_parts: list[dict] | None = None

    if session is not None:
        prompt_after, prompt_parts = resolve_prompt_default(session, True)

    return build_display(
        with_leading_blank_lines(
            _build_lore_error_parts(
                message,
                session,
                error_code=error_code,
                error_context=error_context,
            )
        ),
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
