from assets import get_gear_template_by_id
from combat_state import get_engaged_entity, get_entity_condition, get_health_condition, is_entity_hostile_to_player
from equipment_logic import list_worn_items
from item_logic import _build_corpse_label, _item_highlight_color
from models import ClientSession
from player_resources import get_player_resource_caps
from session_registry import list_authenticated_room_players
from targeting_entities import list_room_corpses, list_room_entities
from world import Room, get_room

from display_core import _panel_divider, _panel_title_line, build_display, build_part, newline_part, with_leading_blank_lines
from display_feedback import _direction_short_label, _direction_sort_key, resolve_prompt_default
from room_exits import describe_exit_status


def _resolve_posture_label(*, is_sitting: bool, is_resting: bool, is_sleeping: bool) -> str:
    if is_sleeping:
        return "sleeping"
    if is_resting:
        return "resting"
    if is_sitting:
        return "sitting"
    return "standing"


def _append_posture_parts(parts: list[dict], *, is_sitting: bool, is_resting: bool, is_sleeping: bool) -> None:
    posture_label = _resolve_posture_label(is_sitting=is_sitting, is_resting=is_resting, is_sleeping=is_sleeping)
    parts.extend([
        build_part(" (", "display_room.summary.label"),
        build_part(posture_label, "display_room.summary.label"),
        build_part(")", "display_room.summary.label"),
    ])


def _scan_visible_hostiles(session: ClientSession, room_id: str) -> list:
    visible = [
        entity
        for entity in list_room_entities(session, room_id)
        if is_entity_hostile_to_player(session, entity)
    ]
    visible.sort(key=lambda entity: (entity.name.lower(), entity.spawn_sequence))
    return visible


def _scan_visible_unhostiles(session: ClientSession, room_id: str) -> list:
    visible = [
        entity
        for entity in list_room_entities(session, room_id)
        if entity.is_alive and not is_entity_hostile_to_player(session, entity)
    ]
    visible.sort(key=lambda entity: (entity.name.lower(), entity.spawn_sequence))
    return visible


def _scan_visible_players(session: ClientSession, room_id: str) -> list[ClientSession]:
    visible = list_authenticated_room_players(room_id, exclude_client_id=session.client_id)
    visible.sort(key=lambda player_session: (player_session.authenticated_character_name.lower(), player_session.client_id))
    return visible


def _append_scan_entity_summary(
    parts: list[dict],
    entities: list,
    *,
    prefix: str,
    name_color: str,
    count_color: str = "display_room.scan.count",
) -> bool:
    if not entities:
        return False

    summarized: list[dict[str, str | int]] = []
    for entity in entities:
        normalized_name = entity.name.strip().lower()
        if summarized and str(summarized[-1]["normalized_name"]) == normalized_name:
            summarized[-1]["count"] = int(summarized[-1]["count"]) + 1
            continue

        summarized.append({
            "normalized_name": normalized_name,
            "name": entity.name,
            "count": 1,
        })

    if prefix:
        parts.append(build_part(prefix, "feedback.text", True))

    for index, entry in enumerate(summarized):
        if index > 0:
            parts.append(build_part(", ", "feedback.text"))

        parts.append(build_part(str(entry["name"]), name_color, True))
        count = int(entry["count"])
        if count > 1:
            parts.append(build_part(f" [{count}]", count_color, True))

    return True


def _append_scan_hostile_summary(parts: list[dict], entities: list, *, prefix: str = "Enemies: ") -> bool:
    return _append_scan_entity_summary(parts, entities, prefix=prefix, name_color="display_room.scan.hostile")


def _append_scan_unhostile_summary(parts: list[dict], entities: list, *, prefix: str = "Unhostile: ") -> bool:
    return _append_scan_entity_summary(parts, entities, prefix=prefix, name_color="display_room.scan.neutral")


def _append_scan_npc_summary(
    parts: list[dict],
    hostiles: list,
    unhostiles: list,
    *,
    prefix: str = "NPCs: ",
) -> bool:
    if not hostiles and not unhostiles:
        return False

    if prefix:
        parts.append(build_part(prefix, "display_room.scan.prefix", True))

    appended = False
    if hostiles:
        _append_scan_entity_summary(parts, hostiles, prefix="", name_color="display_room.scan.hostile")
        appended = True

    if unhostiles:
        if appended:
            parts.append(build_part(", ", "display_room.scan.separator"))
        _append_scan_entity_summary(parts, unhostiles, prefix="", name_color="display_room.scan.neutral")
        appended = True

    return appended


def _append_scan_player_summary(parts: list[dict], players: list[ClientSession], *, prefix: str = "Players: ") -> bool:
    if not players:
        return False

    summarized: list[dict[str, str | int]] = []
    for player_session in players:
        player_name = player_session.authenticated_character_name.strip() or "Unknown"
        normalized_name = player_name.lower()
        if summarized and str(summarized[-1]["normalized_name"]) == normalized_name:
            summarized[-1]["count"] = int(summarized[-1]["count"]) + 1
            continue

        summarized.append({
            "normalized_name": normalized_name,
            "name": player_name,
            "count": 1,
        })

    if prefix:
        parts.append(build_part(prefix, "display_room.scan.prefix", True))

    for index, entry in enumerate(summarized):
        if index > 0:
            parts.append(build_part(", ", "display_room.scan.separator"))

        parts.append(build_part(str(entry["name"]), "display_room.scan.player", True))
        count = int(entry["count"])
        if count > 1:
            parts.append(build_part(f" [{count}]", "display_room.scan.player_count", True))

    return True


def display_exits(session: ClientSession, room: Room) -> dict:
    prompt_after, prompt_parts = resolve_prompt_default(session, True)
    exit_items = sorted(room.exits.items(), key=lambda item: _direction_sort_key(item[0]))

    parts: list[dict] = [
        build_part(_panel_title_line("Exits"), "display_room.exits.title", True),
        newline_part(),
        build_part(_panel_divider(), "display_room.exits.divider"),
    ]

    if not exit_items:
        parts.extend([
            newline_part(),
            build_part("No visible exits.", "display_room.exits.empty"),
        ])
    else:
        direction_width = max(len(str(direction).strip().title()) for direction, _ in exit_items)
        for direction, destination_room_id in exit_items:
            destination_room = get_room(destination_room_id)
            destination_label = destination_room.title if destination_room is not None else str(destination_room_id)
            parts.extend([
                newline_part(),
                build_part(f"[{_direction_short_label(direction)}]", "display_room.exits.direction_short", True),
                build_part(" ", "display_room.summary.label"),
                build_part(str(direction).strip().title().ljust(direction_width), "display_room.exits.direction_name", True),
                build_part(" -> ", "display_room.exits.arrow"),
                build_part(destination_label, "display_room.exits.destination", True),
                build_part(describe_exit_status(room, direction), "display_room.exits.status"),
            ])

            nearby_hostiles = _scan_visible_hostiles(session, destination_room_id)
            nearby_unhostiles = _scan_visible_unhostiles(session, destination_room_id)
            nearby_players = _scan_visible_players(session, destination_room_id)
            if nearby_hostiles or nearby_unhostiles or nearby_players:
                parts.append(build_part(" - ", "display_room.exits.arrow"))
                appended_summary = False
                if nearby_hostiles or nearby_unhostiles:
                    appended_summary = _append_scan_npc_summary(parts, nearby_hostiles, nearby_unhostiles, prefix="NPCs: ")
                if nearby_players:
                    if appended_summary:
                        parts.append(build_part(" | ", "display_room.exits.arrow"))
                    _append_scan_player_summary(parts, nearby_players, prefix="Players: ")

    visible_enemies = _scan_visible_hostiles(session, room.room_id)
    visible_unhostiles = _scan_visible_unhostiles(session, room.room_id)
    visible_players = _scan_visible_players(session, room.room_id)
    if visible_enemies or visible_unhostiles or visible_players:
        parts.extend([
            newline_part(),
            build_part(_panel_divider(), "display_room.exits.divider"),
            newline_part(),
            build_part("Here: ", "display_room.exits.here_label", True),
        ])
        appended_summary = False
        if visible_enemies or visible_unhostiles:
            appended_summary = _append_scan_npc_summary(parts, visible_enemies, visible_unhostiles, prefix="NPCs: ")
        if visible_players:
            if appended_summary:
                parts.append(build_part(" | ", "display_room.exits.arrow"))
            _append_scan_player_summary(parts, visible_players, prefix="Players: ")

    return build_display(with_leading_blank_lines(parts), prompt_after=prompt_after, prompt_parts=prompt_parts)


def _summarize_entity_gear(entity) -> list[str]:
    visible_items: list[str] = []

    main_template_id = str(getattr(entity, "main_hand_weapon_template_id", "")).strip()
    if main_template_id:
        template = get_gear_template_by_id(main_template_id)
        item_name = str(template.get("name", "Weapon")).strip() if template else main_template_id
        visible_items.append(f"Main Hand: {item_name}")

    off_template_id = str(getattr(entity, "off_hand_weapon_template_id", "")).strip()
    if off_template_id:
        template = get_gear_template_by_id(off_template_id)
        item_name = str(template.get("name", "Off-hand")).strip() if template else off_template_id
        visible_items.append(f"Off Hand: {item_name}")

    return visible_items


def _summarize_player_gear(target_session: ClientSession) -> list[str]:
    return [f"{slot.title()}: {item.name}" for slot, item in list_worn_items(target_session)]


def _display_look_summary(
    session: ClientSession,
    *,
    title: str,
    title_color: str,
    condition_text: str,
    condition_color: str,
    gear_summary: list[str],
) -> dict:
    prompt_after, prompt_parts = resolve_prompt_default(session, True)
    parts = [
        build_part(_panel_title_line(title), title_color, True),
        newline_part(),
        build_part(_panel_divider(), "display_room.summary.divider"),
        newline_part(),
        build_part("Condition: ", "display_room.summary.label", True),
        build_part(condition_text.title(), condition_color, True),
        newline_part(),
        build_part("Gear:", "display_room.summary.label", True),
    ]

    if gear_summary:
        for gear_line in gear_summary:
            parts.extend([
                newline_part(),
                build_part(" - ", "display_room.summary.label"),
                build_part(gear_line, "display_room.summary.gear", True),
            ])
    else:
        parts.extend([
            newline_part(),
            build_part("No obvious gear.", "display_room.summary.empty"),
        ])

    return build_display(with_leading_blank_lines(parts), prompt_after=prompt_after, prompt_parts=prompt_parts)


def display_entity_summary(session: ClientSession, entity) -> dict:
    condition_text, condition_color = get_entity_condition(entity)
    return _display_look_summary(
        session,
        title=entity.name,
        title_color="display_room.entity_summary.title",
        condition_text=condition_text,
        condition_color=condition_color,
        gear_summary=_summarize_entity_gear(entity),
    )


def display_player_summary(session: ClientSession, target_session: ClientSession) -> dict:
    caps = get_player_resource_caps(target_session)
    condition_text, condition_color = get_health_condition(target_session.status.hit_points, caps["hit_points"])
    target_name = target_session.authenticated_character_name.strip() or "Player"
    return _display_look_summary(
        session,
        title=target_name,
        title_color="display_room.player_summary.title",
        condition_text=condition_text,
        condition_color=condition_color,
        gear_summary=_summarize_player_gear(target_session),
    )


def _display_character_name(target_session: ClientSession) -> str:
    return str(target_session.authenticated_character_name).strip() or "Unknown"


def _resolve_entity_engagement_target_name(current_session: ClientSession, entity) -> str | None:
    entity_id = str(getattr(entity, "entity_id", "")).strip()
    if not entity_id:
        return None

    if entity_id in current_session.combat.engaged_entity_ids:
        return _display_character_name(current_session)

    room_players = list_authenticated_room_players(
        str(getattr(entity, "room_id", "")).strip(),
        exclude_client_id=current_session.client_id,
    )
    for player_session in room_players:
        if entity_id in player_session.combat.engaged_entity_ids:
            return _display_character_name(player_session)
    return None


def _resolve_player_engagement_target_name(target_session: ClientSession) -> str | None:
    engaged_entity = get_engaged_entity(target_session)
    if engaged_entity is None:
        return None
    if not getattr(engaged_entity, "is_alive", False):
        return None
    if str(getattr(engaged_entity, "room_id", "")).strip() != str(target_session.player.current_room_id).strip():
        return None
    return str(getattr(engaged_entity, "name", "")).strip() or "Unknown"


def _append_room_engagement_parts(parts: list[dict], target_name: str | None, *, is_you: bool = False) -> None:
    if not target_name:
        return

    verb_text = "Fighting " if is_you else "fighting "
    label_text = "YOU!" if is_you else target_name
    parts.extend([
        build_part(" (", "display_room.summary.label"),
        build_part(verb_text, "display_room.status.verb"),
        build_part(label_text, "display_room.status.label", True),
        build_part(")", "display_room.summary.label"),
    ])


def display_room(session: ClientSession, room: Room) -> dict:
    prompt_after, prompt_parts = resolve_prompt_default(session, True)

    parts = [
        build_part(room.title, "display_room.room.title", True),
        newline_part(),
        build_part(room.description, "display_room.room.description"),
    ]

    entities = list_room_entities(session, room.room_id)
    if entities:
        parts.extend([
            newline_part(),
            newline_part(),
            build_part("You see here:", "display_room.section.heading", True),
        ])

        for entity in entities:
            entity_name_color = "display_room.entity.hostile" if is_entity_hostile_to_player(session, entity) else "display_room.entity.neutral"
            parts.extend([
                newline_part(),
                build_part(" - ", "display_room.section.bullet"),
                build_part(entity.name, entity_name_color, True),
            ])
            _append_posture_parts(
                parts,
                is_sitting=bool(getattr(entity, "is_sitting", False)),
                is_resting=bool(getattr(entity, "is_resting", False)),
                is_sleeping=bool(getattr(entity, "is_sleeping", False)),
            )
            engagement_target = _resolve_entity_engagement_target_name(session, entity)
            _append_room_engagement_parts(
                parts,
                engagement_target,
                is_you=bool(engagement_target) and engagement_target == _display_character_name(session),
            )

    other_players = list_authenticated_room_players(room.room_id, exclude_client_id=session.client_id)
    if other_players:
        parts.extend([
            newline_part(),
            newline_part(),
            build_part("Players here:", "display_room.section.heading", True),
        ])

        for other_player in other_players:
            player_name = other_player.authenticated_character_name.strip() or "Unknown"
            parts.extend([
                newline_part(),
                build_part(" - ", "display_room.section.bullet"),
                build_part(player_name, "display_room.player.name", True),
            ])
            _append_posture_parts(
                parts,
                is_sitting=bool(getattr(other_player, "is_sitting", False)),
                is_resting=bool(getattr(other_player, "is_resting", False)),
                is_sleeping=bool(getattr(other_player, "is_sleeping", False)),
            )
            _append_room_engagement_parts(parts, _resolve_player_engagement_target_name(other_player))

    corpses = list_room_corpses(session, room.room_id)

    room_coin_amount = max(0, int(session.room_coin_piles.get(room.room_id, 0)))
    if room_coin_amount > 0:
        parts.extend([
            newline_part(),
            newline_part(),
            build_part("Coin pile:", "display_room.section.heading", True),
            newline_part(),
            build_part(" - ", "display_room.section.bullet"),
            build_part(str(room_coin_amount), "display_room.coin.amount", True),
            build_part(" coins", "display_room.summary.label"),
        ])

    room_items = list(session.room_ground_items.get(room.room_id, {}).values())
    room_items.sort(key=lambda item: item.name.lower())

    ground_item_counts: dict[str, int] = {}
    ground_item_names: dict[str, str] = {}
    ground_item_colors: dict[str, str] = {}
    ground_item_order: list[str] = []

    for corpse in corpses:
        corpse_name = _build_corpse_label(
            corpse.source_name,
            getattr(corpse, "corpse_label_style", "generic"),
            is_named=bool(getattr(corpse, "is_named", False)),
        )
        normalized = corpse_name.strip().lower()
        if not normalized:
            continue
        if normalized not in ground_item_counts:
            ground_item_counts[normalized] = 0
            ground_item_names[normalized] = corpse_name
            ground_item_colors[normalized] = "item_logic.highlight.item"
            ground_item_order.append(normalized)
        ground_item_counts[normalized] += 1

    for item in room_items:
        normalized = item.name.strip().lower()
        if not normalized:
            continue
        if normalized not in ground_item_counts:
            ground_item_counts[normalized] = 0
            ground_item_names[normalized] = item.name
            ground_item_colors[normalized] = _item_highlight_color(item)
            ground_item_order.append(normalized)
        ground_item_counts[normalized] += 1

    if ground_item_order:
        ground_item_order.sort(key=lambda item_key: ground_item_names[item_key].lower())
        parts.extend([
            newline_part(),
            newline_part(),
            build_part("On the ground:", "display_room.section.heading", True),
        ])
        for item_key in ground_item_order:
            parts.extend([
                newline_part(),
                build_part(" - ", "display_room.section.bullet"),
                build_part(ground_item_names[item_key], ground_item_colors[item_key], True),
            ])
            count = ground_item_counts[item_key]
            if count > 1:
                parts.extend([
                    build_part(" ", "display_room.summary.label"),
                    build_part(f"[{count}]", "display_room.item.count", True),
                ])

    return build_display(with_leading_blank_lines(parts), prompt_after=prompt_after, prompt_parts=prompt_parts)
