import asyncio
import uuid

from models import ClientSession, EntityState


COMBAT_ROUND_INTERVAL_SECONDS = 1.5


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
    target_id = session.engaged_entity_id
    if target_id is None:
        return

    entity = session.entities.get(target_id)
    if entity is None or not entity.is_alive or entity.room_id != session.player.current_room_id:
        session.engaged_entity_id = None
        session.next_combat_round_monotonic = None


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


def begin_attack(session: ClientSession, target_name: str) -> dict:
    from display import build_part, display_command_result, display_error
    clear_combat_if_invalid(session)
    entity = find_room_entity_by_name(session, session.player.current_room_id, target_name)

    if entity is None:
        return display_error(f"No target named '{target_name}' is here.", session)

    session.engaged_entity_id = entity.entity_id
    session.next_combat_round_monotonic = asyncio.get_running_loop().time() + COMBAT_ROUND_INTERVAL_SECONDS

    return display_command_result(session, [
        build_part("You engage ", "bright_white"),
        build_part(entity.name, "bright_red", True),
        build_part(".", "bright_white"),
    ])


def disengage(session: ClientSession) -> dict:
    from display import build_part, display_command_result, display_error
    clear_combat_if_invalid(session)

    if session.engaged_entity_id is None:
        return display_error("You are not engaged with anything.", session)

    entity = session.entities.get(session.engaged_entity_id)
    session.engaged_entity_id = None
    session.next_combat_round_monotonic = None

    target_name = entity.name if entity is not None else "your target"
    return display_command_result(session, [
        build_part("You disengage from ", "bright_white"),
        build_part(target_name, "bright_yellow", True),
        build_part(".", "bright_white"),
    ])


def resolve_combat_round(session: ClientSession) -> dict | None:
    from display import build_part, display_command_result
    clear_combat_if_invalid(session)

    target_id = session.engaged_entity_id
    if target_id is None:
        return None

    entity = session.entities.get(target_id)
    if entity is None or not entity.is_alive or entity.room_id != session.player.current_room_id:
        clear_combat_if_invalid(session)
        return None

    parts: list[dict] = []
    player = session.player

    for _ in range(max(1, player.attacks_per_round)):
        if not entity.is_alive:
            break

        entity.hit_points = max(0, entity.hit_points - player.attack_damage)
        parts.extend([
            build_part("You hit ", "bright_white"),
            build_part(entity.name, "bright_red", True),
            build_part(" for ", "bright_white"),
            build_part(str(player.attack_damage), "bright_yellow", True),
            build_part(" damage", "bright_white"),
            build_part(f" ({entity.hit_points}/{entity.max_hit_points} HP).", "bright_white"),
            build_part("\n"),
        ])

    if entity.hit_points <= 0:
        entity.is_alive = False
        session.engaged_entity_id = None
        session.next_combat_round_monotonic = None
        player.coins += entity.coin_reward

        parts.extend([
            build_part(entity.name, "bright_red", True),
            build_part(" is destroyed. ", "bright_white"),
            build_part("Coins +", "bright_white"),
            build_part(str(entity.coin_reward), "bright_yellow", True),
            build_part(".", "bright_white"),
        ])

        return display_command_result(session, parts)

    for _ in range(max(1, entity.attacks_per_round)):
        player.hit_points = max(0, player.hit_points - entity.attack_damage)
        parts.extend([
            build_part(entity.name, "bright_red", True),
            build_part(" hits you for ", "bright_white"),
            build_part(str(entity.attack_damage), "bright_yellow", True),
            build_part(" damage", "bright_white"),
            build_part(f" ({player.hit_points} HP).", "bright_white"),
            build_part("\n"),
        ])

    if player.hit_points <= 0:
        if player.extra_lives > 0:
            player.extra_lives -= 1
            player.hit_points = 575
            player.vigor = 119
            session.engaged_entity_id = None
            session.next_combat_round_monotonic = None
            parts.extend([
                build_part("You collapse, then recover using an extra life. Combat ends.", "bright_magenta", True),
            ])
        else:
            session.engaged_entity_id = None
            session.next_combat_round_monotonic = None
            parts.extend([
                build_part("You collapse. Combat ends.", "bright_red", True),
            ])
            return display_command_result(session, parts)

    session.next_combat_round_monotonic = asyncio.get_running_loop().time() + COMBAT_ROUND_INTERVAL_SECONDS
    return display_command_result(session, parts)
