"""Companion lifecycle helpers: enlisting, roster persistence, follow, and cleanup.

Companions are EntityState instances living in the shared world dict, tagged
with ``is_companion`` and an ``owner_player_key`` matching the owning session's
combatant key. They are never ClientSessions and never enter group_member_keys;
the group display, movement, and combat loops merge them in explicitly.
"""

import uuid

from assets import get_npc_template_by_id
from combat_state import get_session_combatant_key
from models import ClientSession, EntityState
from session_registry import active_character_sessions, connected_clients, shared_world_entities
from settings import MAX_COMPANIONS_PER_PLAYER


def list_owned_companions(owner_key: str) -> list[EntityState]:
    normalized_owner_key = str(owner_key).strip().lower()
    if not normalized_owner_key:
        return []

    companions = [
        entity
        for entity in shared_world_entities.values()
        if entity.is_companion
        and entity.is_alive
        and entity.owner_player_key == normalized_owner_key
    ]
    companions.sort(key=lambda entity: entity.spawn_sequence)
    return companions


def list_owned_companions_for_session(session: ClientSession) -> list[EntityState]:
    return list_owned_companions(get_session_combatant_key(session))


def list_owned_companions_in_room(session: ClientSession) -> list[EntityState]:
    room_id = session.player.current_room_id
    return [
        companion
        for companion in list_owned_companions_for_session(session)
        if companion.room_id == room_id
    ]


def any_live_companions_exist() -> bool:
    return any(
        entity.is_companion and entity.is_alive
        for entity in shared_world_entities.values()
    )


def resolve_room_recruiter(session: ClientSession) -> tuple[EntityState | None, str | None]:
    recruiters = [
        entity
        for entity in session.entities.values()
        if entity.room_id == session.player.current_room_id
        and entity.is_alive
        and bool(getattr(entity, "is_recruiter", False))
    ]
    recruiters.sort(key=lambda entity: (entity.name.lower(), -entity.spawn_sequence, entity.entity_id))
    if not recruiters:
        return None, "There is no recruiter here."
    return recruiters[0], None


def spawn_companion_for_session(session: ClientSession, npc_id: str) -> tuple[EntityState | None, str | None]:
    from world_population import _build_entity_from_template

    owner_key = get_session_combatant_key(session)
    if not owner_key:
        return None, "You cannot enlist companions right now."

    template = get_npc_template_by_id(npc_id)
    if template is None or not bool(template.get("is_companion", False)):
        return None, f"No companion is known by '{npc_id}'."

    next_spawn_sequence = max((entity.spawn_sequence for entity in session.entities.values()), default=0) + 1
    session.entity_spawn_counter = max(session.entity_spawn_counter, next_spawn_sequence)

    companion = _build_entity_from_template(template, session.player.current_room_id, next_spawn_sequence)
    companion.entity_id = f"companion-{uuid.uuid4().hex[:8]}"
    companion.owner_player_key = owner_key
    companion.is_ally = True
    companion.respawn = False
    companion.wander_chance = 0.0
    session.entities[companion.entity_id] = companion
    return companion, None


def despawn_companion_entities_for_session(session: ClientSession) -> list[EntityState]:
    """Remove the session's live companion entities from the world.

    The companion roster is left untouched so the companions respawn on the
    owner's next login.
    """
    removed: list[EntityState] = []
    for companion in list_owned_companions_for_session(session):
        shared_world_entities.pop(companion.entity_id, None)
        removed.append(companion)
    return removed


def remove_companion_roster_entry(session: ClientSession, npc_id: str) -> bool:
    normalized_npc_id = str(npc_id).strip().lower()
    for index, entry in enumerate(session.companion_roster):
        if str(entry.get("npc_id", "")).strip().lower() == normalized_npc_id:
            session.companion_roster.pop(index)
            return True
    return False


def respawn_roster_companions(session: ClientSession) -> list[EntityState]:
    """Spawn the roster's companions at the owner's current room.

    Idempotent for reconnect takeover: roster entries already backed by a live
    owned entity (matched by npc_id count) are reattached, not respawned.
    """
    owner_key = get_session_combatant_key(session)
    if not owner_key:
        return []

    live_counts: dict[str, int] = {}
    for companion in list_owned_companions(owner_key):
        normalized_npc_id = companion.npc_id.strip().lower()
        live_counts[normalized_npc_id] = live_counts.get(normalized_npc_id, 0) + 1

    spawned: list[EntityState] = []
    for entry in list(session.companion_roster):
        npc_id = str(entry.get("npc_id", "")).strip()
        normalized_npc_id = npc_id.lower()
        if not npc_id:
            continue
        if live_counts.get(normalized_npc_id, 0) > 0:
            live_counts[normalized_npc_id] -= 1
            continue

        companion, spawn_error = spawn_companion_for_session(session, npc_id)
        if companion is None:
            # Content changed since the roster was saved; drop the stale entry.
            if spawn_error is not None:
                remove_companion_roster_entry(session, npc_id)
            continue
        spawned.append(companion)

    return spawned


def handle_companion_defeat(session: ClientSession, companion: EntityState) -> None:
    """Resolve a companion death: corpse, world removal, and roster loss."""
    from combat_state import spawn_corpse_for_entity
    from player_state_db import save_player_state

    companion.is_alive = False
    companion.hit_points = 0
    companion.coin_reward = 0
    companion.experience_reward = 0
    spawn_corpse_for_entity(session, companion)
    shared_world_entities.pop(companion.entity_id, None)
    if remove_companion_roster_entry(session, companion.npc_id) and session.player_state_key.strip():
        save_player_state(session)


def move_companions_with_owner(owner_session: ClientSession, from_room_id: str, to_room_id: str) -> list[EntityState]:
    owner_key = get_session_combatant_key(owner_session)
    moved: list[EntityState] = []
    for companion in list_owned_companions(owner_key):
        if companion.room_id != from_room_id:
            continue
        companion.room_id = to_room_id
        moved.append(companion)
    return moved


def companion_roster_has_capacity(session: ClientSession) -> bool:
    return len(session.companion_roster) < MAX_COMPANIONS_PER_PLAYER


def _resolve_owner_session(owner_key: str) -> ClientSession | None:
    normalized_key = str(owner_key).strip().lower()
    if not normalized_key:
        return None

    for candidate in connected_clients.values():
        if not candidate.is_authenticated or not candidate.is_connected or candidate.disconnected_by_server:
            continue
        if get_session_combatant_key(candidate) == normalized_key:
            return candidate

    # Presence in active_character_sessions means the character is still live
    # in the world, even when disconnected_by_server is set from an earlier
    # forced disconnect; the offline safe-disconnect path pops the entry.
    offline = active_character_sessions.get(normalized_key)
    if offline is not None and offline.is_authenticated:
        return offline
    return None


def collect_stray_companion_moves() -> list[tuple[EntityState, str, str]]:
    """Leash companions back to their owner's room.

    Returns (companion, from_room_id, to_room_id) tuples for the caller to
    broadcast. Companions whose owner no longer exists in either session
    registry are removed from the world outright.
    """
    if not any_live_companions_exist():
        return []

    moves: list[tuple[EntityState, str, str]] = []
    for companion in list(shared_world_entities.values()):
        if not companion.is_companion or not companion.is_alive:
            continue

        owner_session = _resolve_owner_session(companion.owner_player_key)
        if owner_session is None:
            shared_world_entities.pop(companion.entity_id, None)
            continue
        if owner_session.pending_death_logout:
            continue

        owner_room_id = owner_session.player.current_room_id
        if not owner_room_id or companion.room_id == owner_room_id:
            continue

        from_room_id = companion.room_id
        companion.room_id = owner_room_id
        moves.append((companion, from_room_id, owner_room_id))

    return moves
