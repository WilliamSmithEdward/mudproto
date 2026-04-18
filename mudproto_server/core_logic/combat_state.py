"""Combat state, engagement, timer, and corpse lifecycle helpers."""

import asyncio
import random
import uuid

from assets import get_gear_template_by_id
from combat_ability_effects import process_entity_battle_round_tick
from display_core import build_display, build_part, resolve_display_color, with_leading_blank_lines
from inventory import build_equippable_item_from_template
from models import ClientSession, CorpseState, EntityState, ItemState
from session_registry import active_character_sessions, connected_clients, shared_world_entities, shared_world_flags
from settings import COMBAT_ROUND_INTERVAL_SECONDS, HEALTH_CONDITION_BANDS
from targeting_entities import list_room_entities, resolve_room_entity_selector


_pending_auto_aggro_due_monotonic: dict[str, float] = {}


def get_health_condition(hit_points: int, max_hit_points: int) -> tuple[str, str]:
    if max_hit_points <= 0:
        return "awful", resolve_display_color("feedback.error")

    ratio = max(0.0, min(1.0, hit_points / max_hit_points))
    for band in HEALTH_CONDITION_BANDS:
        max_ratio = max(0.0, min(1.0, float(band.get("max_ratio", 1.0))))
        if ratio <= max_ratio:
            label = str(band.get("label", "perfect")).strip().lower() or "perfect"
            color = str(band.get("color", resolve_display_color("feedback.success"))).strip() or resolve_display_color("feedback.success")
            return label, color

    return "perfect", resolve_display_color("feedback.success")


def get_entity_condition(entity: EntityState) -> tuple[str, str]:
    return get_health_condition(entity.hit_points, entity.max_hit_points)


def spawn_corpse_for_entity(session: ClientSession, entity: EntityState) -> CorpseState:
    next_spawn_sequence = max((corpse.spawn_sequence for corpse in session.corpses.values()), default=0) + 1
    session.corpse_spawn_counter = max(session.corpse_spawn_counter, next_spawn_sequence)
    corpse_id = f"corpse-{uuid.uuid4().hex[:8]}"
    loot_items: dict[str, ItemState] = {}

    equipped_template_ids: list[tuple[str, float]] = []
    if entity.main_hand_weapon_template_id.strip():
        equipped_template_ids.append((
            entity.main_hand_weapon_template_id.strip(),
            float(getattr(entity, "main_hand_weapon_drop_on_death", 0.0) or 0.0),
        ))
    if entity.off_hand_weapon_template_id.strip():
        equipped_template_ids.append((
            entity.off_hand_weapon_template_id.strip(),
            float(getattr(entity, "off_hand_weapon_drop_on_death", 0.0) or 0.0),
        ))

    for template_id, drop_chance in equipped_template_ids:
        if drop_chance <= 0.0 or (random.random() * 100.0) >= drop_chance:
            continue

        template = get_gear_template_by_id(template_id)
        if template is None:
            continue

        loot_item = build_equippable_item_from_template(template, item_id=f"loot-{uuid.uuid4().hex[:8]}")
        loot_items[loot_item.item_id] = loot_item

    for carried_item in list(getattr(entity, "inventory_items", [])):
        if not isinstance(carried_item, ItemState):
            continue
        loot_items[carried_item.item_id] = carried_item

    entity.inventory_items = []

    corpse = CorpseState(
        corpse_id=corpse_id,
        source_entity_id=entity.entity_id,
        source_name=entity.name,
        room_id=entity.room_id,
        is_named=bool(getattr(entity, "is_named", False)),
        corpse_label_style=str(getattr(entity, "corpse_label_style", "generic")).strip().lower() or "generic",
        coins=max(0, entity.coin_reward),
        loot_items=loot_items,
        spawn_sequence=next_spawn_sequence,
    )
    session.corpses[corpse_id] = corpse
    return corpse


def clear_combat_if_invalid(session: ClientSession) -> None:
    current_room_id = session.player.current_room_id
    invalid_entities = set()

    for entity_id in session.combat.engaged_entity_ids:
        entity = session.entities.get(entity_id)
        if entity is None or not entity.is_alive or entity.room_id != current_room_id:
            invalid_entities.add(entity_id)

    session.combat.engaged_entity_ids -= invalid_entities

    for entity_id in invalid_entities:
        entity = session.entities.get(entity_id)
        if entity is not None:
            sync_entity_target_player(entity)

    if not session.combat.engaged_entity_ids:
        end_combat(session)


def end_combat(session: ClientSession) -> None:
    disengaged_entity_ids = list(session.combat.engaged_entity_ids)
    session.combat.engaged_entity_ids.clear()
    session.combat.next_round_monotonic = None
    session.combat.opening_attacker = None

    for entity_id in disengaged_entity_ids:
        entity = session.entities.get(entity_id)
        if entity is not None:
            sync_entity_target_player(entity)


def _active_player_flags(session: ClientSession) -> set[str]:
    return {
        " ".join(str(flag).strip().lower().split())
        for flag, enabled in getattr(session.player, "interaction_flags", {}).items()
        if enabled and str(flag).strip()
    }


def _entity_should_auto_aggro(session: ClientSession, entity: EntityState) -> bool:
    if bool(getattr(entity, "is_aggro", False)):
        return True

    active_flags = _active_player_flags(session)
    if not active_flags:
        return False

    entity_flags = {
        " ".join(str(flag).strip().lower().split())
        for flag in getattr(entity, "aggro_player_flags", [])
        if str(flag).strip()
    }
    return bool(entity_flags & active_flags)


def is_entity_hostile_to_player(session: ClientSession, entity: EntityState) -> bool:
    if entity is None or not bool(getattr(entity, "is_alive", False)):
        return False
    if bool(getattr(entity, "is_ally", False)):
        return False
    if str(getattr(entity, "entity_id", "")).strip() in getattr(session.combat, "engaged_entity_ids", set()):
        return True
    if bool(getattr(entity, "is_peaceful", False)):
        return False
    return _entity_should_auto_aggro(session, entity)


def _apply_player_hostile_action_flags(session: ClientSession, entity: EntityState) -> None:
    for raw_flag in getattr(entity, "set_player_flags_on_hostile_action", []):
        normalized_flag = " ".join(str(raw_flag).strip().lower().split())
        if normalized_flag:
            session.player.interaction_flags[normalized_flag] = True


def get_session_combatant_key(session: ClientSession | None) -> str:
    if session is None:
        return ""
    player_state_key = str(getattr(session, "player_state_key", "")).strip().lower()
    client_id = str(getattr(session, "client_id", "")).strip().lower()
    return player_state_key or client_id


def _get_entity_engaged_sessions(entity: EntityState) -> list[ClientSession]:
    sessions_by_key: dict[str, ClientSession] = {}
    for sess in list(connected_clients.values()) + list(active_character_sessions.values()):
        session_key = get_session_combatant_key(sess)
        if not session_key or session_key in sessions_by_key:
            continue
        if not sess.is_authenticated or not sess.is_connected or sess.disconnected_by_server:
            continue
        if sess.pending_death_logout or sess.status.hit_points <= 0:
            continue
        if sess.player.current_room_id != entity.room_id:
            continue
        if entity.entity_id not in sess.combat.engaged_entity_ids:
            continue
        sessions_by_key[session_key] = sess

    return sorted(
        sessions_by_key.values(),
        key=lambda sess: ((sess.authenticated_character_name or "").lower(), sess.client_id),
    )


def sync_entity_target_player(entity: EntityState, preferred_session: ClientSession | None = None) -> str:
    engaged_sessions = _get_entity_engaged_sessions(entity)
    current_target_key = str(getattr(entity, "combat_target_player_key", "")).strip().lower()
    if current_target_key and any(get_session_combatant_key(sess) == current_target_key for sess in engaged_sessions):
        return current_target_key

    preferred_target_key = get_session_combatant_key(preferred_session)
    if preferred_target_key and any(get_session_combatant_key(sess) == preferred_target_key for sess in engaged_sessions):
        entity.combat_target_player_key = preferred_target_key
        return preferred_target_key

    if engaged_sessions:
        fallback_target_key = get_session_combatant_key(engaged_sessions[0])
        entity.combat_target_player_key = fallback_target_key
        return fallback_target_key

    entity.combat_target_player_key = ""
    return ""


def rescue_player(rescuer_session: ClientSession, rescued_session: ClientSession) -> tuple[EntityState | None, str | None]:
    rescuer_key = get_session_combatant_key(rescuer_session)
    rescued_key = get_session_combatant_key(rescued_session)
    rescued_name = (rescued_session.authenticated_character_name or "Your ally").strip() or "Your ally"

    if not rescuer_key or not rescued_key:
        return None, f"{rescued_name} cannot be reached through the chaos of battle."
    if rescuer_key == rescued_key:
        return None, "You are already standing in the thick of danger."

    targeted_entities = [
        entity
        for entity in get_engaged_entities(rescued_session)
        if entity.is_alive
        and entity.room_id == rescued_session.player.current_room_id
        and str(getattr(entity, "combat_target_player_key", "")).strip().lower() == rescued_key
    ]
    if not targeted_entities:
        return None, f"{rescued_name} needs no rescuing; no foe has them pinned."

    redirected_entity = targeted_entities[0]
    rescuing_from_idle = not bool(rescuer_session.combat.engaged_entity_ids)
    rescuer_session.combat.engaged_entity_ids.add(redirected_entity.entity_id)
    rescued_session.combat.engaged_entity_ids.discard(redirected_entity.entity_id)
    redirected_entity.combat_target_player_key = rescuer_key

    rescuer_session.combat.next_round_monotonic = None
    if rescuing_from_idle:
        rescuer_session.combat.opening_attacker = None

    remaining_targeted_entities = [
        entity
        for entity in get_engaged_entities(rescued_session)
        if str(getattr(entity, "combat_target_player_key", "")).strip().lower() == rescued_key
    ]
    if not remaining_targeted_entities:
        end_combat(rescued_session)
        redirected_entity.combat_target_player_key = rescuer_key

    return redirected_entity, None


def start_combat(
    session: ClientSession,
    entity_id: str,
    opening_attacker: str,
    *,
    trigger_player_auto_aggro: bool = True,
) -> bool:
    already_engaged = entity_id in session.combat.engaged_entity_ids
    was_in_combat = bool(session.combat.engaged_entity_ids)

    entity = session.entities.get(entity_id)
    if entity is None or not entity.is_alive:
        return False
    if bool(getattr(entity, "is_peaceful", False)):
        return False
    if entity.room_id != session.player.current_room_id:
        return False

    session.combat.engaged_entity_ids.add(entity_id)
    sync_entity_target_player(entity, preferred_session=session)

    if opening_attacker == "player":
        _apply_player_hostile_action_flags(session, entity)
        if trigger_player_auto_aggro:
            for candidate in list_room_entities(session, session.player.current_room_id):
                if candidate.entity_id == entity_id or not candidate.is_alive:
                    continue
                if bool(getattr(candidate, "is_peaceful", False)):
                    continue
                if not _entity_should_auto_aggro(session, candidate):
                    continue
                if _is_entity_engaged_by_other_player(candidate.entity_id, session):
                    continue
                session.combat.engaged_entity_ids.add(candidate.entity_id)

    session.combat.next_round_monotonic = None
    if not was_in_combat and not session.combat.opening_attacker:
        session.combat.opening_attacker = opening_attacker
    return not already_engaged


def apply_entity_defeat_flags(session: ClientSession, entity: EntityState) -> None:
    interaction_flags = dict(getattr(session.player, "interaction_flags", {}) or {})
    for raw_flag in getattr(entity, "set_player_flags_on_death", []):
        normalized_flag = " ".join(str(raw_flag).strip().lower().split())
        if normalized_flag:
            interaction_flags[normalized_flag] = True
    session.player.interaction_flags = interaction_flags

    for raw_flag in getattr(entity, "set_world_flags_on_death", []):
        normalized_flag = " ".join(str(raw_flag).strip().lower().split())
        if normalized_flag:
            shared_world_flags.add(normalized_flag)

    world_flags_added = bool(getattr(entity, "set_world_flags_on_death", []))
    if world_flags_added:
        from world_population import process_zone_flag_spawns
        process_zone_flag_spawns()


def _display_peaceful_warning(session: ClientSession, entity: EntityState) -> dict:
    from display_feedback import resolve_prompt_default

    prompt_after, prompt_parts = resolve_prompt_default(session, True)
    return build_display(
        with_leading_blank_lines([
            build_part("Relax. ", "feedback.warning", True),
            build_part(f"{entity.name} is peaceful.", "feedback.text"),
        ]),
        prompt_after=prompt_after,
        prompt_parts=prompt_parts,
        is_error=True,
    )


def _find_peaceful_target(
    session: ClientSession,
    *,
    target_name: str | None = None,
    include_room_scan: bool = False,
) -> EntityState | None:
    if target_name:
        entity, _ = resolve_room_entity_selector(
            session,
            session.player.current_room_id,
            target_name,
            living_only=True,
        )
        if entity is not None and bool(getattr(entity, "is_peaceful", False)):
            return entity

    if include_room_scan:
        for entity in list_room_entities(session, session.player.current_room_id):
            if entity.is_alive and bool(getattr(entity, "is_peaceful", False)):
                return entity

    return None


def _schedule_next_combat_round(session: ClientSession) -> None:
    try:
        now = asyncio.get_running_loop().time()
    except RuntimeError:
        session.combat.next_round_monotonic = None
        return

    session.combat.next_round_monotonic = now + COMBAT_ROUND_INTERVAL_SECONDS


def get_engaged_entities(session: ClientSession) -> list[EntityState]:
    clear_combat_if_invalid(session)

    entities = []
    for entity_id in session.combat.engaged_entity_ids:
        entity = session.entities.get(entity_id)
        if entity is not None:
            entities.append(entity)
    entities.sort(key=lambda item: item.spawn_sequence)
    return entities


def get_engaged_entity(session: ClientSession) -> EntityState | None:
    """Get primary engaged entity (first in set for player attacks)."""
    entities = get_engaged_entities(session)
    return entities[0] if entities else None


def _engage_next_targeting_entity(
    session: ClientSession,
    defeated_entity_id: str,
    active_target_entity_ids: set[str] | None = None,
) -> EntityState | None:
    """Select next target only from entities currently engaging this player."""
    candidates: list[EntityState] = []
    for candidate in get_engaged_entities(session):
        if candidate.entity_id == defeated_entity_id:
            continue
        if not candidate.is_alive:
            continue
        if active_target_entity_ids is not None and candidate.entity_id not in active_target_entity_ids:
            continue
        candidates.append(candidate)

    if candidates:
        next_target = candidates[0]
        session.combat.opening_attacker = None
        _schedule_next_combat_round(session)
        return next_target

    end_combat(session)
    return None


def _process_combat_round_timers(session: ClientSession, entities: list[EntityState]) -> None:
    from battle_round_ticks import process_player_battle_round_tick

    process_player_battle_round_tick(session)

    for entity in entities:
        process_entity_battle_round_tick(entity)


def _consume_entity_action_lag(entity: EntityState) -> bool:
    if entity.skill_lag_rounds_remaining > 0:
        entity.skill_lag_rounds_remaining -= 1
    if entity.spell_lag_rounds_remaining <= 0:
        return False
    entity.spell_lag_rounds_remaining -= 1
    return True


def _is_entity_engaged_by_other_player(entity_id: str, current_session: ClientSession) -> bool:
    """Check if an entity is already engaged by any other player."""
    for sess in connected_clients.values():
        if sess != current_session and entity_id in sess.combat.engaged_entity_ids:
            return True

    for sess in active_character_sessions.values():
        if sess != current_session and entity_id in sess.combat.engaged_entity_ids:
            return True

    return False


def _list_valid_auto_aggro_targets_for_entity(entity: EntityState) -> list[ClientSession]:
    room_id = str(getattr(entity, "room_id", "")).strip()
    if not room_id:
        return []

    candidates_by_key: dict[str, ClientSession] = {}
    for sess in list(connected_clients.values()) + list(active_character_sessions.values()):
        session_key = get_session_combatant_key(sess)
        if not session_key or session_key in candidates_by_key:
            continue
        if not sess.is_authenticated or not sess.is_connected or sess.disconnected_by_server:
            continue
        if sess.pending_death_logout or sess.status.hit_points <= 0:
            continue
        if sess.player.current_room_id != room_id:
            continue
        if not _entity_should_auto_aggro(sess, entity):
            continue
        candidates_by_key[session_key] = sess

    return list(candidates_by_key.values())


def process_pending_auto_aggro() -> None:
    if not _pending_auto_aggro_due_monotonic:
        return

    try:
        now = asyncio.get_running_loop().time()
    except RuntimeError:
        return

    due_entity_ids = [
        entity_id
        for entity_id, due_at in list(_pending_auto_aggro_due_monotonic.items())
        if now >= float(due_at)
    ]
    if not due_entity_ids:
        return

    for entity_id in due_entity_ids:
        _pending_auto_aggro_due_monotonic.pop(entity_id, None)

        entity = shared_world_entities.get(entity_id)
        if entity is None or not getattr(entity, "is_alive", False):
            continue
        if _get_entity_engaged_sessions(entity):
            continue

        candidates = _list_valid_auto_aggro_targets_for_entity(entity)
        if not candidates:
            continue

        chosen_session = random.choice(candidates)
        start_combat(chosen_session, entity.entity_id, "entity")


def maybe_auto_engage_current_room(session: ClientSession) -> list[EntityState]:
    clear_combat_if_invalid(session)
    if session.combat.engaged_entity_ids:
        return []

    engaged_entities: list[EntityState] = []
    room_entities = list_room_entities(session, session.player.current_room_id)
    for entity in room_entities:
        if _get_entity_engaged_sessions(entity):
            continue
        if entity.entity_id in _pending_auto_aggro_due_monotonic:
            continue

        candidates = _list_valid_auto_aggro_targets_for_entity(entity)
        if not candidates:
            continue

        try:
            now = asyncio.get_running_loop().time()
        except RuntimeError:
            continue

        # Delay auto-aggro start and choose target when the delay expires.
        _pending_auto_aggro_due_monotonic[entity.entity_id] = now + random.uniform(0.25, 0.75)

    return engaged_entities
