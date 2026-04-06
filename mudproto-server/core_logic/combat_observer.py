"""Observer and room-broadcast text helpers for combat."""

import re

from grammar import resolve_player_pronouns
from session_registry import active_character_sessions


def _attach_room_broadcast_lines(outbound: dict, lines: list[str]) -> dict:
    payload = outbound.get("payload")
    if not isinstance(payload, dict):
        return outbound

    broadcast_lines: list[list[dict]] = []
    for line in lines:
        cleaned = str(line).strip()
        if not cleaned:
            continue

        is_death_line = cleaned.lower().endswith(" is dead!")
        fg = "bright_red" if is_death_line else "bright_white"
        bold = is_death_line
        broadcast_lines.append([
            {"text": cleaned, "fg": fg, "bold": bold}
        ])

    if broadcast_lines:
        payload["room_broadcast_lines"] = broadcast_lines
    return outbound


def _render_observer_template(template_text: str, actor_name: str, actor_gender: str | None = None) -> str:
    resolved_gender = actor_gender
    if not resolved_gender:
        normalized_actor_name = actor_name.strip().lower()
        for active_session in active_character_sessions.values():
            if active_session.authenticated_character_name.strip().lower() == normalized_actor_name:
                resolved_gender = active_session.player.gender
                break

    actor_subject, actor_object, actor_possessive, _ = resolve_player_pronouns(
        actor_name=actor_name,
        actor_gender=resolved_gender,
    )
    return (
        template_text
        .replace("[actor_name]", actor_name)
        .replace("[actor_subject]", actor_subject)
        .replace("[actor_object]", actor_object)
        .replace("[actor_possessive]", actor_possessive)
    )


def _observer_context_from_player_context(context: str, target_text: str | None = None) -> str:
    if not context:
        return ""

    resolved = context
    resolved = resolved.replace("[a/an]", target_text or "the target")
    resolved = resolved.replace("[verb]", "is")
    resolved = resolved.replace(" your ", " their ")
    resolved = resolved.replace(" you ", " them ")
    resolved = resolved.replace(" yourself", " themselves")
    if resolved.startswith("Your "):
        resolved = f"Their {resolved[5:]}"
    if resolved.startswith("You "):
        resolved = f"{resolved[4:]}"
    return resolved


def _resolve_combat_context(context: str, *, target_text: str, verb: str) -> str:
    resolved = str(context).strip()
    if not resolved:
        return ""

    resolved = resolved.replace("[a/an]", target_text)
    resolved = resolved.replace("[verb]", verb)

    if target_text.strip().lower() == "you":
        resolved = re.sub(r"\byou is\b", "you are", resolved, flags=re.IGNORECASE)
        resolved = re.sub(r"\byou has\b", "you have", resolved, flags=re.IGNORECASE)
        if resolved.startswith("you "):
            resolved = f"You{resolved[3:]}"

    if resolved and not resolved.endswith("."):
        resolved += "."
    return resolved


def _default_observer_action_line(
    actor_name: str,
    action_verb: str,
    ability_name: str,
    cast_type: str,
    target_label: str | None = None,
) -> str:
    if cast_type == "self":
        return f"{actor_name} {action_verb} {ability_name} on themselves."
    if cast_type == "target" and target_label:
        return f"{actor_name} {action_verb} {ability_name} on {target_label}."
    if cast_type == "aoe":
        return f"{actor_name} {action_verb} {ability_name} across the room."
    return f"{actor_name} {action_verb} {ability_name}."


def _normalize_observer_sentence(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return ""
    if normalized[-1] not in ".!?":
        normalized += "."
    return normalized


def _resolve_observer_action_line(
    actor_name: str,
    action_verb: str,
    ability_name: str,
    cast_type: str,
    target_label: str | None = None,
    observer_action: str = "",
) -> str:
    canonical_line = _default_observer_action_line(actor_name, action_verb, ability_name, cast_type, target_label)
    rendered_custom = _normalize_observer_sentence(_render_observer_template(observer_action, actor_name))
    if not rendered_custom:
        return canonical_line

    lowered = rendered_custom.lower()

    if cast_type == "self" and "on themselves" not in lowered:
        return f"{rendered_custom.rstrip('.!?')} on themselves."

    if cast_type == "aoe" and "across the room" not in lowered:
        return f"{rendered_custom.rstrip('.!?')} across the room."

    if cast_type == "target" and target_label:
        lowered_target = target_label.lower()
        if f" on {lowered_target}" not in lowered and f" at {lowered_target}" not in lowered:
            return f"{rendered_custom.rstrip('.!?')} on {target_label}."

    return rendered_custom
