import asyncio
import random
import uuid

from models import ClientSession, EntityState


COMBAT_ROUND_INTERVAL_SECONDS = 2.5
FLEE_SUCCESS_CHANCE = 0.5


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
        session.combat.engaged_entity_id = None
        session.combat.next_round_monotonic = None


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
            session.combat.engaged_entity_id = entity.entity_id
            session.combat.next_round_monotonic = asyncio.get_running_loop().time() + COMBAT_ROUND_INTERVAL_SECONDS
            return entity

    return None


def build_auto_aggro_notice(entity: EntityState) -> list[dict]:
    from display import build_part

    return [
        build_part("\n"),
        build_part("\n"),
        build_part(entity.name, "bright_red", True),
        build_part(" notices you and attacks!", "bright_white"),
    ]


def build_auto_aggro_outbound(session: ClientSession, room_display: dict) -> list[dict]:
    from display import display_force_prompt

    auto_entity = maybe_auto_engage_current_room(session)
    if auto_entity is None:
        return [room_display]

    room_display["payload"]["prompt_after"] = False
    room_display["payload"]["prompt_text"] = None
    room_display["payload"]["parts"].extend(build_auto_aggro_notice(auto_entity))

    combat_result = resolve_combat_round(session)
    if combat_result is None:
        return [room_display, display_force_prompt(session)]

    return [room_display, combat_result, display_force_prompt(session)]


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

    session.combat.engaged_entity_id = entity.entity_id
    combat_result = resolve_combat_round(session)

    if combat_result is None:
        session.combat.next_round_monotonic = asyncio.get_running_loop().time() + COMBAT_ROUND_INTERVAL_SECONDS
        return display_force_prompt(session)

    return [combat_result, display_force_prompt(session)]


def disengage(session: ClientSession) -> dict | list[dict]:
    from display import build_part, display_command_result, display_error

    clear_combat_if_invalid(session)

    if session.combat.engaged_entity_id is None:
        return display_error("You are not engaged with anything.", session)

    entity = session.entities.get(session.combat.engaged_entity_id)
    session.combat.engaged_entity_id = None
    session.combat.next_round_monotonic = None

    target_name = entity.name if entity is not None else "your target"
    return display_command_result(session, [
        build_part("You disengage from ", "bright_white"),
        build_part(target_name, "bright_yellow", True),
        build_part(".", "bright_white"),
    ])


def flee(session: ClientSession) -> dict | list[dict]:
    from display import build_part, display_command_result, display_error, display_room
    from world import get_room

    clear_combat_if_invalid(session)
    if session.combat.engaged_entity_id is None:
        return display_error("You are not engaged with anything.", session)

    current_room = get_room(session.player.current_room_id)
    if current_room is None:
        return display_error(f"Current room not found: {session.player.current_room_id}", session)

    exits = list(current_room.exits.items())
    if not exits:
        return display_error("There is nowhere to flee.", session)

    if random.random() >= FLEE_SUCCESS_CHANCE:
        entity = session.entities.get(session.combat.engaged_entity_id)
        target_name = entity.name if entity is not None else "your attacker"
        return display_command_result(session, [
            build_part("You try to flee from ", "bright_white"),
            build_part(target_name, "bright_red", True),
            build_part(", but fail.", "bright_white"),
        ])

    flee_direction, next_room_id = random.choice(exits)
    next_room = get_room(next_room_id)
    if next_room is None:
        return display_error(f"Destination room not found: {next_room_id}", session)

    session.player.current_room_id = next_room.room_id
    session.combat.engaged_entity_id = None
    session.combat.next_round_monotonic = None

    room_display = display_room(session, next_room)
    room_display["payload"]["parts"] = [
        build_part("You flee ", "bright_white"),
        build_part(flee_direction, "bright_yellow", True),
        build_part(".", "bright_white"),
        build_part("\n"),
        build_part("\n"),
    ] + room_display["payload"]["parts"]

    return build_auto_aggro_outbound(session, room_display)


def _append_newline_if_needed(parts: list[dict]) -> None:
    if parts:
        parts.append({"text": "\n", "fg": "bright_white", "bold": False})


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
    player = session.player_combat
    status = session.status

    for _ in range(max(1, player.attacks_per_round)):
        if not entity.is_alive:
            break

        _append_newline_if_needed(parts)
        entity.hit_points = max(0, entity.hit_points - player.attack_damage)
        parts.extend([
            build_part("You hit ", "bright_white"),
            build_part(entity.name, "bright_red", True),
            build_part(" for ", "bright_white"),
            build_part(str(player.attack_damage), "bright_yellow", True),
            build_part(" damage", "bright_white"),
            build_part(f" ({entity.hit_points}/{entity.max_hit_points} HP).", "bright_white"),
        ])

    if entity.hit_points <= 0:
        entity.is_alive = False
        session.combat.engaged_entity_id = None
        session.combat.next_round_monotonic = None
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

    if status.hit_points <= 0:
        session.combat.engaged_entity_id = None
        session.combat.next_round_monotonic = None

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