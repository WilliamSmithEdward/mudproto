"""Configurable room and NPC keyword interactions plus action application."""

from attribute_config import player_class_uses_mana
from assets import get_gear_template_by_id, get_item_template_by_id, get_npc_template_by_id
from display_core import build_line, build_part, newline_part, parts_to_lines
from display_feedback import display_command_result, display_error
from experience import award_experience
from display_room import display_exits, display_room
from inventory import build_equippable_item_from_template, build_misc_item_from_template
from models import ClientSession
from player_resources import roll_level_resource_gains
from session_registry import shared_world_flags
from targeting_entities import list_room_entities
from world import Room, get_room


_REVEAL_EXIT_ACTIONS = {"set_exit", "reveal_exit", "show_exit"}
_HIDE_EXIT_ACTIONS = {"hide_exit", "remove_exit", "unset_exit"}


def _normalize_keyword_text(text: str) -> str:
    return " ".join(str(text).strip().lower().split())


def _render_keyword_text(message: str, *, session: ClientSession, room: Room | None, actor_name: str = "") -> str:
    rendered = str(message).strip()
    if not rendered:
        return ""

    replacements = {
        "[player_name]": session.authenticated_character_name.strip() or "traveller",
        "[room_name]": getattr(room, "name", "") or "",
        "[npc_name]": actor_name.strip(),
    }
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    return rendered


def _active_player_flags(session: ClientSession | None) -> set[str]:
    if session is None:
        return set()
    return {
        str(flag_key).strip().lower()
        for flag_key, is_enabled in dict(getattr(session.player, "interaction_flags", {}) or {}).items()
        if str(flag_key).strip() and bool(is_enabled)
    }


def _active_world_flags() -> set[str]:
    return {
        str(flag).strip().lower()
        for flag in shared_world_flags
        if str(flag).strip()
    }


def _entry_matches_player_flags(
    entry: dict,
    active_flags: set[str],
    active_world_flags: set[str] | None = None,
    session: ClientSession | None = None,
) -> bool:
    required_flags = {
        str(flag).strip().lower()
        for flag in entry.get("required_player_flags", [])
        if str(flag).strip()
    }
    excluded_flags = {
        str(flag).strip().lower()
        for flag in entry.get("excluded_player_flags", [])
        if str(flag).strip()
    }
    normalized_world_flags = active_world_flags or set()
    required_world_flags = {
        str(flag).strip().lower()
        for flag in entry.get("required_world_flags", [])
        if str(flag).strip()
    }
    excluded_world_flags = {
        str(flag).strip().lower()
        for flag in entry.get("excluded_world_flags", [])
        if str(flag).strip()
    }
    required_item_template_ids = {
        str(template_id).strip().lower()
        for template_id in entry.get("required_item_template_ids", [])
        if str(template_id).strip()
    }
    excluded_item_template_ids = {
        str(template_id).strip().lower()
        for template_id in entry.get("excluded_item_template_ids", [])
        if str(template_id).strip()
    }
    session_item_template_ids: set[str] = set()
    if session is not None:
        session_item_template_ids = {
            str(getattr(item, "template_id", "")).strip().lower()
            for item in list(session.inventory_items.values()) + list(session.equipment.equipped_items.values())
            if str(getattr(item, "template_id", "")).strip()
        }
    return (
        required_flags.issubset(active_flags)
        and not bool(active_flags & excluded_flags)
        and required_world_flags.issubset(normalized_world_flags)
        and not bool(normalized_world_flags & excluded_world_flags)
        and required_item_template_ids.issubset(session_item_template_ids)
        and not bool(session_item_template_ids & excluded_item_template_ids)
    )


def _apply_player_flag_updates(session: ClientSession | None, entry: dict) -> bool:
    changed = False

    if session is not None:
        interaction_flags = dict(getattr(session.player, "interaction_flags", {}) or {})

        for flag in entry.get("set_player_flags", []):
            normalized_flag = str(flag).strip().lower()
            if not normalized_flag or bool(interaction_flags.get(normalized_flag, False)):
                continue
            interaction_flags[normalized_flag] = True
            changed = True

        for flag in entry.get("clear_player_flags", []):
            normalized_flag = str(flag).strip().lower()
            if not normalized_flag or normalized_flag not in interaction_flags:
                continue
            interaction_flags.pop(normalized_flag, None)
            changed = True

        if changed:
            session.player.interaction_flags = interaction_flags

    normalized_world_flags = _active_world_flags()
    for flag in entry.get("set_world_flags", []):
        normalized_flag = str(flag).strip().lower()
        if not normalized_flag or normalized_flag in normalized_world_flags:
            continue
        shared_world_flags.add(normalized_flag)
        normalized_world_flags.add(normalized_flag)
        changed = True

    for flag in entry.get("clear_world_flags", []):
        normalized_flag = str(flag).strip().lower()
        if not normalized_flag or normalized_flag not in normalized_world_flags:
            continue
        shared_world_flags.discard(normalized_flag)
        normalized_world_flags.discard(normalized_flag)
        changed = True

    return changed


def _prepend_message(outbound: dict, message: str) -> dict:
    payload = outbound.get("payload") if isinstance(outbound, dict) else None
    if not isinstance(payload, dict) or not str(message).strip():
        return outbound

    lines = payload.get("lines")
    if not isinstance(lines, list):
        return outbound

    normalized_existing = [line for line in lines if isinstance(line, list)]
    while normalized_existing and not normalized_existing[0]:
        normalized_existing.pop(0)

    payload["lines"] = [
        build_line(build_part(message, "feedback.text")),
        [],
        *normalized_existing,
    ]
    return outbound


def _session_has_template_item(session: ClientSession, template_id: str) -> bool:
    normalized_template_id = str(template_id).strip().lower()
    if not normalized_template_id:
        return False

    for item in session.inventory_items.values():
        if str(getattr(item, "template_id", "")).strip().lower() == normalized_template_id:
            return True

    for item in session.equipment.equipped_items.values():
        if str(getattr(item, "template_id", "")).strip().lower() == normalized_template_id:
            return True

    return False


def _grant_template_item(session: ClientSession, template_id: str) -> bool:
    gear_template = get_gear_template_by_id(template_id)
    item_template = get_item_template_by_id(template_id) if gear_template is None else None
    resolved_template = gear_template or item_template
    if resolved_template is None:
        return False

    if gear_template is not None:
        granted_item = build_equippable_item_from_template(gear_template)
    else:
        granted_item = build_misc_item_from_template(resolved_template)
    session.inventory_items[granted_item.item_id] = granted_item
    return True


def _remove_template_item(session: ClientSession, template_id: str, quantity: int = 1) -> int:
    normalized_template_id = str(template_id).strip().lower()
    if not normalized_template_id:
        return 0

    removed_count = 0
    for item_id, item in list(session.inventory_items.items()):
        if str(getattr(item, "template_id", "")).strip().lower() != normalized_template_id:
            continue
        session.inventory_items.pop(item_id, None)
        removed_count += 1
        if removed_count >= max(1, quantity):
            return removed_count

    for item_id, item in list(session.equipment.equipped_items.items()):
        if str(getattr(item, "template_id", "")).strip().lower() != normalized_template_id:
            continue
        session.equipment.equipped_items.pop(item_id, None)
        if session.equipment.equipped_main_hand_id == item_id:
            session.equipment.equipped_main_hand_id = None
        if session.equipment.equipped_off_hand_id == item_id:
            session.equipment.equipped_off_hand_id = None
        session.equipment.worn_item_ids = {
            slot: equipped_item_id
            for slot, equipped_item_id in session.equipment.worn_item_ids.items()
            if equipped_item_id != item_id
        }
        removed_count += 1
        if removed_count >= max(1, quantity):
            return removed_count

    return removed_count


def _build_level_up_lines(session: ClientSession, old_level: int, new_level: int) -> list[list[dict]]:
    if new_level <= old_level:
        return []
    resource_gains = roll_level_resource_gains(session, old_level, new_level)
    show_mana = player_class_uses_mana(session.player.class_id)
    parts: list[dict] = []
    parts.append(newline_part())
    parts.extend([
        build_part("You advance to level ", "combat_rewards.level_up", True),
        build_part(str(new_level), "combat_rewards.level_up", True),
        build_part("!", "combat_rewards.level_up", True),
    ])
    parts.append(newline_part())
    parts.extend([
        build_part("Level gains: ", "combat_rewards.text"),
        build_part(f"+{int(resource_gains.get('hit_points', 0))}HP", "combat_rewards.gain.hp", True),
        build_part(" ", "combat_rewards.text"),
        build_part(f"+{int(resource_gains.get('vigor', 0))}V", "combat_rewards.gain.vigor", True),
    ])
    if show_mana:
        parts.extend([
            build_part(" ", "combat_rewards.text"),
            build_part(f"+{int(resource_gains.get('mana', 0))}M", "combat_rewards.gain.mana", True),
        ])
    parts.append(newline_part())
    return parts_to_lines(parts)


def _apply_keyword_actions(room: Room | None, keyword_action: dict, *, session: ClientSession | None = None) -> tuple[bool, list[list[dict]]]:
    changed = False
    level_up_lines: list[list[dict]] = []
    _apply_player_flag_updates(session, keyword_action)

    for action in keyword_action.get("actions", []):
        action_type = str(action.get("type", "")).strip().lower()
        if action_type == "grant_item":
            if session is None:
                continue

            template_id = str(action.get("template_id", "")).strip()
            quantity = max(1, int(action.get("quantity", 1)))
            if_missing = bool(action.get("if_missing", True))
            if if_missing and _session_has_template_item(session, template_id):
                continue

            granted_any = False
            for _ in range(quantity):
                granted_any = _grant_template_item(session, template_id) or granted_any
            changed = changed or granted_any
            continue

        if action_type == "remove_item":
            if session is None:
                continue

            template_id = str(action.get("template_id", "")).strip()
            quantity = max(1, int(action.get("quantity", 1)))
            removed_count = _remove_template_item(session, template_id, quantity)
            changed = changed or (removed_count > 0)
            continue

        if action_type == "award_experience":
            if session is None:
                continue

            amount = max(0, int(action.get("amount", 0)))
            gained, old_level, new_level, _ = award_experience(session, amount)
            changed = changed or gained > 0 or new_level > old_level
            if new_level > old_level:
                level_up_lines.extend(_build_level_up_lines(session, old_level, new_level))
            continue

        if action_type == "teleport_player":
            if session is None:
                continue

            destination_room_id = str(action.get("destination_room_id", "")).strip()
            if not destination_room_id:
                continue
            if session.player.current_room_id != destination_room_id:
                session.player.current_room_id = destination_room_id
                changed = True
            continue

        if room is None:
            continue

        direction = str(action.get("direction", "")).strip().lower()
        if not direction:
            continue

        if action_type in _REVEAL_EXIT_ACTIONS:
            destination_room_id = str(action.get("destination_room_id", "")).strip()
            if not destination_room_id:
                continue
            if room.exits.get(direction) != destination_room_id:
                room.exits[direction] = destination_room_id
                changed = True
            continue

        if action_type in _HIDE_EXIT_ACTIONS and direction in room.exits:
            room.exits.pop(direction, None)
            changed = True

    return changed, level_up_lines


def _append_lines_to_outbound(outbound: dict, extra_lines: list[list[dict]]) -> None:
    payload = outbound.get("payload") if isinstance(outbound, dict) else None
    if not isinstance(payload, dict) or not extra_lines:
        return
    existing = payload.get("lines", [])
    if not isinstance(existing, list):
        return
    existing.extend(extra_lines)


def _build_room_keyword_outbound(
    session: ClientSession,
    room: Room,
    keyword_action: dict,
    *,
    changed: bool,
    actor_name: str = "",
) -> dict:
    message = _render_keyword_text(
        str(keyword_action.get("message", "")),
        session=session,
        room=room,
        actor_name=actor_name,
    )
    already_message = _render_keyword_text(
        str(keyword_action.get("already_message", "")),
        session=session,
        room=room,
        actor_name=actor_name,
    )
    display_message = message if changed else (already_message or message or "Nothing happens.")

    refresh_view = str(keyword_action.get("refresh_view", "none")).strip().lower() or "none"
    if refresh_view == "none":
        return display_command_result(session, [
            build_part(display_message, "feedback.text"),
        ])

    if refresh_view == "room":
        outbound = display_room(session, room)
    else:
        outbound = display_exits(session, room)

    return _prepend_message(outbound, display_message)


def get_room_enter_communications(
    session: ClientSession,
    room_id: str,
    *,
    apply_state: bool = False,
) -> list[dict[str, str]]:
    room = get_room(room_id)
    if room is None:
        return []

    active_flags = _active_player_flags(session)
    active_world_flags = _active_world_flags()
    entries: list[dict[str, str]] = []
    matched_entries: list[dict] = []
    for entity in list_room_entities(session, room.room_id):
        npc_template = get_npc_template_by_id(getattr(entity, "npc_id", ""))
        if npc_template is None:
            continue

        for communication in npc_template.get("room_communications", []):
            trigger = str(communication.get("trigger", "")).strip().lower()
            if trigger != "player_enter":
                continue
            if not _entry_matches_player_flags(communication, active_flags, active_world_flags, session):
                continue

            message = _render_keyword_text(
                str(communication.get("message", "")),
                session=session,
                room=room,
                actor_name=str(getattr(entity, "name", "")).strip(),
            )
            if not message:
                continue

            matched_entries.append(communication)
            entries.append({
                "message": message,
                "audience": str(communication.get("audience", "both")).strip().lower() or "both",
            })

    if apply_state:
        for communication in matched_entries:
            _apply_player_flag_updates(session, communication)

    return entries


def _line_text(line: list[dict]) -> str:
    return "".join(str(part.get("text", "")) for part in line if isinstance(part, dict)).strip()


def insert_room_communication_lines(outbound: dict, communication_lines: list[list[dict]]) -> dict:
    payload = outbound.get("payload") if isinstance(outbound, dict) else None
    if not isinstance(payload, dict):
        return outbound

    lines = payload.get("lines")
    if not isinstance(lines, list):
        return outbound

    normalized_existing = [line for line in lines if isinstance(line, list)]
    normalized_insert = [line for line in communication_lines if isinstance(line, list)]
    if not normalized_insert:
        return outbound

    section_headers = {"You see here:", "Players here:", "Corpses:", "Coin pile:", "Items on ground:", "On the ground:"}
    insert_index = len(normalized_existing)
    for index, line in enumerate(normalized_existing):
        if _line_text(line) in section_headers:
            insert_index = index
            break

    if insert_index > 0 and _line_text(normalized_existing[insert_index - 1]):
        normalized_insert = [[]] + normalized_insert

    while normalized_insert and insert_index < len(normalized_existing) and not normalized_insert[-1] and not normalized_existing[insert_index]:
        normalized_existing.pop(insert_index)

    payload["lines"] = normalized_existing[:insert_index] + normalized_insert + normalized_existing[insert_index:]
    return outbound


def prepend_room_enter_communications(outbound: dict, session: ClientSession, room_id: str) -> dict:
    communications = get_room_enter_communications(session, room_id, apply_state=True)
    if not communications:
        return outbound

    communication_lines = [
        build_line(build_part(str(entry.get("message", "")).strip(), "feedback.text"))
        for entry in communications
        if str(entry.get("message", "")).strip() and str(entry.get("audience", "both")).strip().lower() in {"private", "both"}
    ]
    if not communication_lines:
        return outbound

    communication_lines.append([])
    return insert_room_communication_lines(outbound, communication_lines)


def _match_keyword_action(keyword_actions: list[dict], normalized_command: str, session: ClientSession | None = None) -> dict | None:
    active_flags = _active_player_flags(session)
    active_world_flags = _active_world_flags()
    for keyword_action in keyword_actions:
        keywords = keyword_action.get("keywords", [])
        if not isinstance(keywords, list):
            continue
        if not _entry_matches_player_flags(keyword_action, active_flags, active_world_flags, session):
            continue
        if any(_normalize_keyword_text(keyword) == normalized_command for keyword in keywords):
            return keyword_action
    return None


def handle_room_keyword_action(session: ClientSession, command_text: str) -> dict | None:
    room = get_room(session.player.current_room_id)
    if room is None:
        return display_error(f"Current room not found: {session.player.current_room_id}", session)

    normalized_command = _normalize_keyword_text(command_text)
    if not normalized_command:
        return None

    keyword_action = _match_keyword_action(room.keyword_actions, normalized_command, session)
    if keyword_action is not None:
        changed, level_up_lines = _apply_keyword_actions(room, keyword_action, session=session)
        active_room = get_room(session.player.current_room_id) or room
        outbound = _build_room_keyword_outbound(session, active_room, keyword_action, changed=changed)
        if level_up_lines:
            _append_lines_to_outbound(outbound, level_up_lines)
        if active_room.room_id != room.room_id:
            prepend_room_enter_communications(outbound, session, active_room.room_id)
        return outbound

    for entity in list_room_entities(session, room.room_id):
        npc_template = get_npc_template_by_id(getattr(entity, "npc_id", ""))
        if npc_template is None:
            continue

        keyword_action = _match_keyword_action(npc_template.get("keyword_actions", []), normalized_command, session)
        if keyword_action is None:
            continue

        changed, level_up_lines = _apply_keyword_actions(room, keyword_action, session=session)
        active_room = get_room(session.player.current_room_id) or room
        outbound = _build_room_keyword_outbound(
            session,
            active_room,
            keyword_action,
            changed=changed,
            actor_name=str(getattr(entity, "name", "")).strip(),
        )
        if level_up_lines:
            _append_lines_to_outbound(outbound, level_up_lines)
        if active_room.room_id != room.room_id:
            prepend_room_enter_communications(outbound, session, active_room.room_id)
        return outbound

    return None
