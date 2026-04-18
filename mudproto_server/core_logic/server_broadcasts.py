"""Room broadcast and outbound-normalization helpers for `server.py`."""

import copy
import re

from display_core import build_display_lines, resolve_display_color
from display_feedback import build_prompt_lines_default, build_prompt_parts_default
from grammar import third_personize_text, to_third_person
from models import ClientSession
from session_registry import connected_clients


def _should_broadcast_to_room(outbound: dict | list[dict]) -> bool:
    messages = outbound if isinstance(outbound, list) else [outbound]
    for message in messages:
        if not isinstance(message, dict):
            continue
        payload = message.get("payload")
        if isinstance(payload, dict) and bool(payload.get("broadcast_to_room", False)):
            return True
    return False


def _iter_room_sessions(room_id: str, *, exclude_client_ids: set[str] | None = None) -> list[ClientSession]:
    normalized_room_id = str(room_id).strip()
    if not normalized_room_id:
        return []

    excluded = {str(client_id).strip() for client_id in (exclude_client_ids or set()) if str(client_id).strip()}
    peers: list[ClientSession] = []
    for session in connected_clients.values():
        if session.client_id in excluded:
            continue
        if not session.is_connected or session.disconnected_by_server or not session.is_authenticated:
            continue
        if session.player.current_room_id != normalized_room_id:
            continue
        peers.append(session)
    return peers


def _iter_room_peers(origin_session: ClientSession) -> list[ClientSession]:
    if not origin_session.is_authenticated:
        return []
    return _iter_room_sessions(origin_session.player.current_room_id, exclude_client_ids={origin_session.client_id})


def _is_private_progression_line(text: str) -> bool:
    normalized = str(text).strip().lower()
    if not normalized:
        return False

    return (
        normalized.startswith("you gain ") and " experience" in normalized
    ) or normalized.startswith("you advance to level ") or normalized.startswith("level gains:")


def _line_text(line: list[dict]) -> str:
    return "".join(str(part.get("text", "")) for part in line if isinstance(part, dict))


def _normalized_line_lists(raw_lines: object) -> list[list[dict]]:
    if not isinstance(raw_lines, list):
        return []
    return [line for line in raw_lines if isinstance(line, list)]


def _contains_player_death_line(lines: list[list[dict]]) -> bool:
    for line in lines:
        normalized = _line_text(line).strip().lower()
        if normalized == "you are dead!" or "mourn your death" in normalized:
            return True
    return False



def _merge_lines_with_pending_private(existing_lines: object, pending_lines: list[list[dict]]) -> list[list[dict]]:
    normalized_existing = _normalized_line_lists(existing_lines)
    if normalized_existing and normalized_existing[-1]:
        normalized_existing.append([])

    merged_lines = normalized_existing + pending_lines
    if merged_lines and merged_lines[-1]:
        merged_lines.append([])
    return merged_lines


def _transform_observer_lines(lines: list[list[dict]], *, actor_name: str, actor_gender: str) -> list[list[dict]]:
    filtered_lines: list[list[dict]] = []
    for line in lines:
        if _is_private_progression_line(_line_text(line)):
            continue
        for part in line:
            if not isinstance(part, dict):
                continue
            original_text = str(part.get("text", ""))
            part["text"] = third_personize_text(original_text, actor_name, actor_gender)
        _prefix_observer_proc_line_actor(line, actor_name)
        _strip_observer_proc_line_style(line)
        _fix_observer_line_grammar(line, actor_name)
        _strip_observer_actor_line_style(line, actor_name)
        filtered_lines.append(line)
    return filtered_lines


def _fix_observer_line_grammar(line: list[dict], actor_name: str) -> None:
    if not isinstance(line, list) or not actor_name.strip():
        return

    running_text = ""
    normalized_actor = actor_name.strip().lower()
    for part in line:
        if not isinstance(part, dict):
            continue

        part_text = str(part.get("text", ""))
        normalized_prefix = running_text.strip().lower()
        if normalized_prefix in {normalized_actor, f"{normalized_actor} barely"}:
            match = re.match(r"^(?P<verb>[A-Za-z]+)(?P<suffix>.*)$", part_text)
            if match is not None:
                verb = str(match.group("verb"))
                suffix = str(match.group("suffix"))
                normalized_verb = verb.strip().lower()
                if normalized_verb not in {"is", "was", "has", "does"}:
                    part["text"] = f"{to_third_person(verb)}{suffix}"
            break

        running_text += part_text


def _strip_observer_actor_line_style(line: list[dict], actor_name: str) -> None:
    if not isinstance(line, list) or not actor_name.strip():
        return

    normalized_text = _line_text(line).strip().lower()
    normalized_actor = actor_name.strip().lower()
    if not normalized_text.startswith(f"{normalized_actor} "):
        return

    observer_color = resolve_display_color("combat.observer.message")
    for part in line:
        if not isinstance(part, dict):
            continue
        part["fg"] = observer_color
        part["bold"] = False


def _strip_observer_proc_line_style(line: list[dict]) -> None:
    if not isinstance(line, list) or not line:
        return

    proc_color = resolve_display_color("combat.proc.message").strip().lower()
    is_proc_line = any(
        isinstance(part, dict)
        and (
            bool(part.get("observer_plain", False))
            or (
                str(part.get("fg", "")).strip().lower() == proc_color
                and bool(part.get("bold", False))
            )
        )
        for part in line
    )
    if not is_proc_line:
        return

    observer_color = resolve_display_color("combat.observer.message")
    for part in line:
        if not isinstance(part, dict):
            continue
        part["fg"] = observer_color
        part["bold"] = False


def _prefix_observer_proc_line_actor(line: list[dict], actor_name: str) -> None:
    if not isinstance(line, list) or not line:
        return

    proc_color = resolve_display_color("combat.proc.message").strip().lower()
    is_proc_line = any(
        isinstance(part, dict)
        and (
            bool(part.get("observer_plain", False))
            or (
                str(part.get("fg", "")).strip().lower() == proc_color
                and bool(part.get("bold", False))
            )
        )
        for part in line
    )
    if not is_proc_line:
        return

    cleaned_actor = str(actor_name).strip() or "Someone"
    line_text = _line_text(line).strip()
    if not line_text:
        return

    lowered_line = line_text.lower()
    lowered_actor = cleaned_actor.lower()
    if lowered_line.startswith(f"{lowered_actor}'s ") or lowered_line.startswith(f"{lowered_actor} "):
        return

    prefixed_text = f"{cleaned_actor}'s {line_text}"
    line[:] = [{
        "text": prefixed_text,
        "fg": resolve_display_color("combat.observer.message"),
        "bold": False,
        "observer_plain": True,
    }]


def _build_room_broadcast_messages(origin_session: ClientSession, outbound: dict | list[dict]) -> list[dict]:
    messages = outbound if isinstance(outbound, list) else [outbound]
    broadcast_messages: list[dict] = []
    actor_name = origin_session.authenticated_character_name or "Someone"

    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("type") != "display":
            continue

        payload = message.get("payload")
        if not isinstance(payload, dict):
            continue

        lines = payload.get("lines")
        if not isinstance(lines, list) or not lines:
            continue

        copied_message = copy.deepcopy(message)
        copied_payload = copied_message.get("payload")
        if isinstance(copied_payload, dict):
            if bool(copied_payload.get("is_error", False)):
                continue

            copied_lines = _normalized_line_lists(copied_payload.get("lines"))
            contains_player_death = _contains_player_death_line(copied_lines)

            observer_lines = copied_payload.get("room_broadcast_lines")
            if isinstance(observer_lines, list) and observer_lines and not contains_player_death:
                copied_payload["lines"] = observer_lines
            else:
                copied_payload["lines"] = _transform_observer_lines(
                    copied_lines,
                    actor_name=actor_name,
                    actor_gender=origin_session.player.gender,
                )

            additional_observer_lines = copied_payload.get("additional_room_broadcast_lines")
            if isinstance(additional_observer_lines, list) and additional_observer_lines and not contains_player_death:
                normalized_additional_lines = _normalized_line_lists(additional_observer_lines)
                normalized_lines = _normalized_line_lists(copied_payload.get("lines"))
                if normalized_lines and normalized_lines[-1]:
                    normalized_lines.append([])
                normalized_lines.extend(normalized_additional_lines)
                copied_payload["lines"] = normalized_lines

            normalized_lines = _normalized_line_lists(copied_payload.get("lines"))
            copied_payload["lines"] = normalized_lines
        broadcast_messages.append(copied_message)

    return broadcast_messages


def _extract_display_lines(message: dict | None) -> list[list[dict]]:
    if not isinstance(message, dict):
        return []
    if message.get("type") != "display":
        return []

    payload = message.get("payload")
    if not isinstance(payload, dict):
        return []

    raw_lines = payload.get("lines")
    if not isinstance(raw_lines, list):
        return []

    extracted_lines = [line for line in raw_lines if isinstance(line, list)]

    while extracted_lines and not _line_text(extracted_lines[0]).strip():
        extracted_lines.pop(0)

    while extracted_lines and not _line_text(extracted_lines[-1]).strip():
        extracted_lines.pop()

    return extracted_lines


def _consume_pending_private_lines(session: ClientSession) -> list[list[dict]]:
    pending_lines = [line for line in session.pending_private_lines if isinstance(line, list)]
    session.pending_private_lines = []
    return pending_lines


def _append_private_lines_to_payload(payload: dict, session: ClientSession) -> None:
    pending_lines = _consume_pending_private_lines(session)
    if not pending_lines:
        return

    payload["lines"] = _merge_lines_with_pending_private(payload.get("lines"), pending_lines)


def _normalize_prompt_spacing(payload: dict) -> None:
    prompt_lines = payload.get("prompt_lines")
    if not isinstance(prompt_lines, list) or not prompt_lines:
        return

    normalized_prompt = [line for line in prompt_lines if isinstance(line, list)]
    while normalized_prompt and not normalized_prompt[0]:
        normalized_prompt.pop(0)

    normalized_existing = _normalized_line_lists(payload.get("lines"))
    if normalized_existing and not normalized_existing[-1]:
        prompt_blank_count = 0
    elif normalized_existing:
        prompt_blank_count = 1
    else:
        prompt_blank_count = 0

    payload["prompt_lines"] = ([[]] * prompt_blank_count) + normalized_prompt


def _inject_private_lines_into_outbound(session: ClientSession, outbound: dict | list[dict]) -> dict | list[dict]:
    pending_lines = _consume_pending_private_lines(session)
    if not pending_lines:
        return outbound

    messages = outbound if isinstance(outbound, list) else [outbound]
    for message in messages:
        if not isinstance(message, dict) or message.get("type") != "display":
            continue
        payload = message.get("payload")
        if not isinstance(payload, dict):
            continue

        payload["lines"] = _merge_lines_with_pending_private(payload.get("lines"), pending_lines)
        _normalize_prompt_spacing(payload)
        return outbound

    notification_message = build_display_lines(
        pending_lines,
        prompt_after=True,
        prompt_parts=build_prompt_parts_default(session),
    )
    if isinstance(outbound, list):
        return [notification_message, *outbound]
    return [notification_message, outbound]


def _split_actor_round_lines(lines: list[list[dict]], actor_prefix: str) -> tuple[list[list[dict]], list[list[dict]]]:
    player_lines: list[list[dict]] = []
    retaliation_lines: list[list[dict]] = []
    in_retaliation = False
    normalized_prefix = actor_prefix.strip().lower()

    def _is_actor_auxiliary_line(line_parts: list[dict]) -> bool:
        if not isinstance(line_parts, list) or not line_parts:
            return False

        line_text = _line_text(line_parts).strip().lower()
        if line_text.endswith(" is dead!"):
            return True

        for part in line_parts:
            if not isinstance(part, dict):
                continue
            if bool(part.get("observer_plain", False)):
                return True
            if str(part.get("fg", "")).strip().lower() == resolve_display_color("combat.proc.message").strip().lower() and bool(part.get("bold", False)):
                return True
        return False

    for line in lines:
        line_text = _line_text(line)
        if not line_text.strip():
            if in_retaliation:
                retaliation_lines.append([])
            else:
                player_lines.append([])
            continue

        normalized_line = line_text.strip().lower()
        is_actor_line = normalized_line.startswith(normalized_prefix)
        if not in_retaliation and (is_actor_line or _is_actor_auxiliary_line(line)):
            player_lines.append(line)
            continue

        in_retaliation = True
        retaliation_lines.append(line)

    return player_lines, retaliation_lines


def _build_unified_room_round_display(
    recipient_session: ClientSession,
    room_round_results: list[tuple[ClientSession, dict]],
) -> dict | None:
    player_phase_lines: list[list[dict]] = []
    retaliation_phase_lines: list[list[dict]] = []

    for actor_session, actor_result in room_round_results:
        actor_name = actor_session.authenticated_character_name or "Someone"
        if recipient_session.client_id == actor_session.client_id:
            recipient_message = actor_result
            actor_prefix = "you "
        else:
            observer_messages = _build_room_broadcast_messages(actor_session, actor_result)
            if not observer_messages:
                continue
            recipient_message = observer_messages[0]
            actor_prefix = f"{actor_name.lower()} "

        lines = _extract_display_lines(recipient_message)
        if not lines:
            continue

        actor_lines, retaliation_lines = _split_actor_round_lines(lines, actor_prefix)
        player_phase_lines.extend(actor_lines)
        retaliation_phase_lines.extend(retaliation_lines)

    merged_lines = player_phase_lines + retaliation_phase_lines
    if not merged_lines:
        return None

    explicit_lines = merged_lines
    if explicit_lines and explicit_lines[-1]:
        explicit_lines.append([])

    return build_display_lines(explicit_lines)


async def _send_room_broadcast(
    origin_session: ClientSession,
    broadcast_messages: list[dict],
    send_outbound_fn,
    *,
    prompt_observers: bool = True,
) -> None:
    if not broadcast_messages:
        return

    peers = _iter_room_peers(origin_session)
    for peer in peers:
        peer_messages = copy.deepcopy(broadcast_messages)
        for message in peer_messages:
            if not isinstance(message, dict) or message.get("type") != "display":
                continue
            payload = message.get("payload")
            if not isinstance(payload, dict):
                continue

            recipient_room_broadcast_lines = payload.pop("recipient_room_broadcast_lines", None)
            if isinstance(recipient_room_broadcast_lines, dict):
                personalized_lines = recipient_room_broadcast_lines.get(peer.client_id)
                if isinstance(personalized_lines, list) and personalized_lines:
                    payload["lines"] = [line for line in personalized_lines if isinstance(line, list)]

            if prompt_observers:
                _append_private_lines_to_payload(payload, peer)
                payload["prompt_lines"] = build_prompt_lines_default(peer)
                _normalize_prompt_spacing(payload)
        await send_outbound_fn(peer.websocket, peer_messages)


async def _broadcast_battle_outbound_to_room(origin_session: ClientSession, outbound: dict | list[dict], send_outbound_fn) -> None:
    broadcast_messages = _build_room_broadcast_messages(origin_session, outbound)
    await _send_room_broadcast(origin_session, broadcast_messages, send_outbound_fn, prompt_observers=True)


async def _broadcast_non_combat_outbound_to_room(origin_session: ClientSession, outbound: dict | list[dict], send_outbound_fn) -> None:
    broadcast_messages = _build_room_broadcast_messages(origin_session, outbound)
    await _send_room_broadcast(origin_session, broadcast_messages, send_outbound_fn, prompt_observers=True)
