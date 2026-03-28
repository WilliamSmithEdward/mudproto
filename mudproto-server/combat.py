import asyncio
import uuid

from equipment import get_held_weapon_name, get_player_attack_damage, get_player_attacks_per_round
from models import ClientSession, EntityState


COMBAT_ROUND_INTERVAL_SECONDS = 2.5
OPENING_ATTACKER_PLAYER = "player"
OPENING_ATTACKER_ENTITY = "entity"


def list_room_entities(session: ClientSession, room_id: str) -> list[EntityState]:
    entities: list[EntityState] = []

    for entity in session.entities.values():
        if entity.is_alive and entity.room_id == room_id:
            entities.append(entity)

    entities.sort(key=lambda item: item.spawn_sequence)
    return entities


def find_room_entity_by_name(session: ClientSession, room_id: str, search_text: str) -> EntityState | None:
    normalized = search_text.strip().lower()
    if not normalized:
        return None

    exact_match: EntityState | None = None
    partial_match: EntityState | None = None

    for entity in list_room_entities(session, room_id):
        entity_name = entity.name.lower()

        if entity_name == normalized:
            exact_match = entity
            break

        if normalized in entity_name and partial_match is None:
            partial_match = entity

    return exact_match or partial_match


def clear_combat_if_invalid(session: ClientSession) -> None:
    target_id = session.combat.engaged_entity_id
    if target_id is None:
        return

    entity = session.entities.get(target_id)
    if entity is None or not entity.is_alive or entity.room_id != session.player.current_room_id:
        end_combat(session)


def end_combat(session: ClientSession) -> None:
    session.combat.engaged_entity_id = None
    session.combat.next_round_monotonic = None
    session.combat.opening_attacker = None


def start_combat(session: ClientSession, entity_id: str, opening_attacker: str) -> None:
    session.combat.engaged_entity_id = entity_id
    session.combat.next_round_monotonic = None
    session.combat.opening_attacker = opening_attacker


def get_engaged_entity(session: ClientSession) -> EntityState | None:
    clear_combat_if_invalid(session)

    target_id = session.combat.engaged_entity_id
    if target_id is None:
        return None

    return session.entities.get(target_id)


def initialize_session_entities(session: ClientSession) -> None:
    if session.entities:
        return

    session.entity_spawn_counter += 1
    scout = EntityState(
        entity_id=f"scout-{uuid.uuid4().hex[:8]}",
        name="Hall Scout",
        room_id="hall",
        hit_points=55,
        max_hit_points=55,
        attack_damage=8,
        attacks_per_round=1,
        coin_reward=20,
        spawn_sequence=session.entity_spawn_counter,
        is_aggro=True,
    )
    session.entities[scout.entity_id] = scout


def maybe_auto_engage_current_room(session: ClientSession) -> EntityState | None:
    clear_combat_if_invalid(session)
    if session.combat.engaged_entity_id is not None:
        return None

    room_entities = list_room_entities(session, session.player.current_room_id)
    for entity in room_entities:
        if entity.is_aggro:
            start_combat(session, entity.entity_id, OPENING_ATTACKER_ENTITY)
            return entity

    return None


def spawn_dummy(session: ClientSession) -> dict:
    from display import build_part, display_command_result

    room_id = session.player.current_room_id
    existing_names = {entity.name for entity in list_room_entities(session, room_id)}

    dummy_number = 1
    dummy_name = "Training Dummy"
    while dummy_name in existing_names:
        dummy_number += 1
        dummy_name = f"Training Dummy {dummy_number}"

    entity_id = f"dummy-{uuid.uuid4().hex[:8]}"
    session.entity_spawn_counter += 1
    entity = EntityState(
        entity_id=entity_id,
        name=dummy_name,
        room_id=room_id,
        hit_points=40,
        max_hit_points=40,
        attack_damage=6,
        attacks_per_round=1,
        coin_reward=12,
        spawn_sequence=session.entity_spawn_counter,
    )
    session.entities[entity_id] = entity

    return display_command_result(session, [
        build_part("Spawned ", "bright_white"),
        build_part(entity.name, "bright_magenta", True),
        build_part(" in this room.", "bright_white"),
    ])


def begin_attack(session: ClientSession, target_name: str) -> dict | list[dict]:
    from display import display_error, display_force_prompt

    clear_combat_if_invalid(session)
    entity = find_room_entity_by_name(session, session.player.current_room_id, target_name)

    if entity is None:
        return display_error(f"No target named '{target_name}' is here.", session)

    start_combat(session, entity.entity_id, OPENING_ATTACKER_PLAYER)
    combat_result = resolve_combat_round(session)

    if combat_result is None:
        session.combat.next_round_monotonic = asyncio.get_running_loop().time() + COMBAT_ROUND_INTERVAL_SECONDS
        return display_force_prompt(session)

    return [combat_result, display_force_prompt(session)]


def disengage(session: ClientSession) -> dict | list[dict]:
    from display import build_part, display_command_result, display_error

    clear_combat_if_invalid(session)

    entity = get_engaged_entity(session)
    if entity is None:
        return display_error("You are not engaged with anything.", session)

    end_combat(session)

    target_name = entity.name if entity is not None else "your target"
    return display_command_result(session, [
        build_part("You disengage from ", "bright_white"),
        build_part(target_name, "bright_yellow", True),
        build_part(".", "bright_white"),
    ])


def _append_newline_if_needed(parts: list[dict]) -> None:
    if parts:
        parts.append({"text": "\n", "fg": "bright_white", "bold": False})


def _apply_player_attacks(session: ClientSession, entity: EntityState, parts: list[dict]) -> None:
    from display import build_part

    attack_damage = get_player_attack_damage(session)
    attacks_per_round = get_player_attacks_per_round(session)
    held_weapon_name = get_held_weapon_name(session)

    for _ in range(attacks_per_round):
        if not entity.is_alive:
            break

        _append_newline_if_needed(parts)
        entity.hit_points = max(0, entity.hit_points - attack_damage)

        attack_parts = [
            build_part("You hit ", "bright_white"),
            build_part(entity.name, "bright_red", True),
        ]
        if held_weapon_name is not None:
            attack_parts.extend([
                build_part(" with ", "bright_white"),
                build_part(held_weapon_name, "bright_cyan", True),
            ])

        attack_parts.extend([
            build_part(" for ", "bright_white"),
            build_part(str(attack_damage), "bright_yellow", True),
            build_part(" damage", "bright_white"),
            build_part(f" ({entity.hit_points}/{entity.max_hit_points} HP).", "bright_white"),
        ])
        parts.extend(attack_parts)


def _apply_entity_attacks(session: ClientSession, entity: EntityState, parts: list[dict]) -> None:
    from display import build_part

    status = session.status

    for _ in range(max(1, entity.attacks_per_round)):
        _append_newline_if_needed(parts)
        status.hit_points = max(0, status.hit_points - entity.attack_damage)
        parts.extend([
            build_part(entity.name, "bright_red", True),
            build_part(" hits you for ", "bright_white"),
            build_part(str(entity.attack_damage), "bright_yellow", True),
            build_part(" damage", "bright_white"),
            build_part(f" ({status.hit_points} HP).", "bright_white"),
        ])


def resolve_combat_round(session: ClientSession) -> dict | None:
    from display import build_part, display_combat_round_result

    clear_combat_if_invalid(session)

    target_id = session.combat.engaged_entity_id
    if target_id is None:
        return None

    entity = session.entities.get(target_id)
    if entity is None or not entity.is_alive or entity.room_id != session.player.current_room_id:
        clear_combat_if_invalid(session)
        return None

    parts: list[dict] = []
    status = session.status
    opening_attacker = session.combat.opening_attacker

    if opening_attacker == OPENING_ATTACKER_ENTITY:
        _apply_entity_attacks(session, entity, parts)
    else:
        _apply_player_attacks(session, entity, parts)

    if entity.hit_points <= 0:
        entity.is_alive = False
        end_combat(session)
        status.coins += entity.coin_reward

        _append_newline_if_needed(parts)
        parts.extend([
            build_part(entity.name, "bright_red", True),
            build_part(" is destroyed. ", "bright_white"),
            build_part("Coins +", "bright_white"),
            build_part(str(entity.coin_reward), "bright_yellow", True),
            build_part(".", "bright_white"),
        ])

        return display_combat_round_result(session, parts)

    if opening_attacker is not None:
        session.combat.opening_attacker = None
    else:
        _apply_entity_attacks(session, entity, parts)

    if status.hit_points <= 0:
        end_combat(session)

        _append_newline_if_needed(parts)
        if status.extra_lives > 0:
            status.extra_lives -= 1
            status.hit_points = 575
            status.vigor = 119
            parts.extend([
                build_part("You collapse, then recover using an extra life. Combat ends.", "bright_magenta", True),
            ])
        else:
            parts.extend([
                build_part("You collapse. Combat ends.", "bright_red", True),
            ])

        return display_combat_round_result(session, parts)

    session.combat.next_round_monotonic = asyncio.get_running_loop().time() + COMBAT_ROUND_INTERVAL_SECONDS
    return display_combat_round_result(session, parts)