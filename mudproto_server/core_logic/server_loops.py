import asyncio
import random

from battle_round_ticks import process_non_combat_support_round
from combat import resolve_combat_round
from combat_ability_effects import process_entity_game_hour_tick
from combat_state import (
    get_engaged_entities,
    get_session_combatant_key,
    maybe_auto_engage_current_room,
    process_pending_auto_aggro,
    sync_entity_target_player,
    tick_out_of_combat_cooldowns,
)
from command_handlers.registry import dispatch_command
from display_feedback import display_error, display_force_prompt, display_prompt
from display_prompts import initial_auth_prompt
from game_hour_ticks import process_game_hour_tick
from models import ClientSession
from player_state_db import save_player_state
from server_broadcasts import (
    _build_unified_room_round_display,
    _broadcast_non_combat_outbound_to_room,
    _inject_private_lines_into_outbound,
    _iter_room_sessions,
    _looks_like_skill_spell_or_item_action,
)
from display_core import build_display, build_part
from server_movement import _handle_movement_side_effects
from server_transport import send_json, send_outbound
from settings import (
    COMBAT_ROUND_INTERVAL_SECONDS,
    COMMAND_SCHEDULER_INTERVAL_SECONDS,
    GAME_TICK_INTERVAL_SECONDS,
)
from session_lifecycle import reset_session_to_login
from session_registry import (
    active_character_sessions,
    connected_clients,
    shared_world_entities,
)
from session_timing import is_session_lagged
from world import WORLD
from world_population import process_world_item_game_hour_tick, repopulate_game_hour_zones


RoomRoundResult = tuple[ClientSession, dict]

next_game_tick_monotonic: float | None = None
next_combat_round_monotonic: float | None = None
next_npc_wander_monotonic: float | None = None


def _entity_is_engaged_by_any_player(entity_id: str) -> bool:
    if not entity_id:
        return False

    seen_session_keys: set[str] = set()
    for session in list(connected_clients.values()) + list(active_character_sessions.values()):
        session_key = (session.player_state_key.strip().lower() or session.client_id)
        if not session_key or session_key in seen_session_keys:
            continue
        seen_session_keys.add(session_key)

        if not session.is_authenticated or session.disconnected_by_server:
            continue
        if entity_id in session.combat.engaged_entity_ids:
            return True

    return False


def _npc_wander_display(parts: list[dict], session: ClientSession) -> dict:
    from display_feedback import build_prompt_parts
    return build_display(
        parts,
        blank_lines_before=0,
        blank_lines_after=0,
        prompt_after=True,
        prompt_parts=build_prompt_parts(session),
    )


def _find_exit_direction(from_room_id: str, to_room_id: str) -> str | None:
    room = WORLD.rooms.get(from_room_id)
    if room is None:
        return None
    for direction, dest in room.exits.items():
        if dest == to_room_id:
            return direction
    return None


async def _process_npc_wandering() -> None:
    from grammar import with_article
    from server_movement import DIRECTION_OPPOSITES, _format_arrival_origin
    for entity in list(shared_world_entities.values()):
        if not getattr(entity, "is_alive", False):
            continue

        if bool(getattr(entity, "is_sitting", False)):
            if int(getattr(entity, "skill_lag_rounds_remaining", 0)) <= 0 and int(getattr(entity, "spell_lag_rounds_remaining", 0)) <= 0:
                entity.is_sitting = False
                stand_parts = [
                    build_part(with_article(entity.name, capitalize=True), "bright_white"),
                    build_part(" stands up.", "bright_white"),
                ]
                for peer in _iter_room_sessions(entity.room_id):
                    await send_outbound(peer.websocket, _npc_wander_display(stand_parts, peer))
            continue

        if _entity_is_engaged_by_any_player(entity.entity_id):
            continue
        wander_chance = getattr(entity, "wander_chance", 0.0)
        if wander_chance <= 0.0:
            continue
        wander_room_ids = getattr(entity, "wander_room_ids", [])
        allowed = set(wander_room_ids)
        current_room = WORLD.rooms.get(entity.room_id)
        candidates = [
            rid for rid in (current_room.exits.values() if current_room else [])
            if rid in allowed and rid in WORLD.rooms
        ]
        if not candidates:
            continue
        if random.random() >= wander_chance:
            continue

        # Re-check engagement immediately before relocating to avoid moving an
        # NPC that got engaged earlier in this tick.
        if _entity_is_engaged_by_any_player(entity.entity_id):
            continue

        origin_room_id = entity.room_id
        dest_room_id = random.choice(candidates)
        entity.room_id = dest_room_id

        entity_label = with_article(entity.name, capitalize=True)
        leave_dir = _find_exit_direction(origin_room_id, dest_room_id)
        arrive_dir = DIRECTION_OPPOSITES.get(leave_dir, "") if leave_dir else ""
        if not arrive_dir:
            arrive_dir = _find_exit_direction(dest_room_id, origin_room_id)

        if leave_dir:
            leave_parts = [
                build_part(entity_label, "bright_white"),
                build_part(f" leaves {leave_dir}.", "bright_white"),
            ]
        else:
            leave_parts = [build_part(f"{entity_label} wanders off.", "bright_white")]

        if arrive_dir:
            arrival_origin = _format_arrival_origin(arrive_dir)
            arrive_parts = [
                build_part(entity_label, "bright_white"),
                build_part(f" arrives from {arrival_origin}.", "bright_white"),
            ]
        else:
            arrive_parts = [build_part(f"{entity_label} wanders in.", "bright_white")]

        for peer in _iter_room_sessions(origin_room_id):
            await send_outbound(peer.websocket, _npc_wander_display(leave_parts, peer))
        for peer in _iter_room_sessions(dest_room_id):
            await send_outbound(peer.websocket, _npc_wander_display(arrive_parts, peer))


def get_next_game_tick_monotonic() -> float | None:
    return next_game_tick_monotonic


async def command_scheduler_loop(session: ClientSession) -> None:
    try:
        while True:
            await asyncio.sleep(COMMAND_SCHEDULER_INTERVAL_SECONDS)

            if session.client_id not in connected_clients:
                break

            now = asyncio.get_running_loop().time()
            while session.next_game_tick_monotonic is not None and now >= session.next_game_tick_monotonic:
                process_game_hour_tick(session)
                if session.is_authenticated:
                    save_player_state(session)
                session.next_game_tick_monotonic += GAME_TICK_INTERVAL_SECONDS

            process_non_combat_support_round(session)

            if session.is_authenticated and not session.combat.engaged_entity_ids:
                maybe_auto_engage_current_room(session)

            if is_session_lagged(session):
                continue

            if session.command_queue:
                queued_command = session.command_queue.pop(0)

                result = dispatch_command(session, queued_command.command_text)
                await _handle_movement_side_effects(session, result, send_outbound)
                result = _inject_private_lines_into_outbound(session, result)
                await send_outbound(session.websocket, result)
                if _looks_like_skill_spell_or_item_action(queued_command.command_text, result):
                    await _broadcast_non_combat_outbound_to_room(session, result, send_outbound)
                continue

            if session.prompt_pending_after_lag:
                session.prompt_pending_after_lag = False
                await send_json(session.websocket, display_prompt(session))

    except asyncio.CancelledError:
        raise
    except Exception as ex:
        error_message = display_error(f"Scheduler failure: {str(ex)}")

        try:
            await send_json(session.websocket, error_message)
        except Exception:
            pass


async def game_tick_loop() -> None:
    global next_game_tick_monotonic

    try:
        next_game_tick_monotonic = asyncio.get_running_loop().time() + GAME_TICK_INTERVAL_SECONDS

        while True:
            sleep_seconds = max(0.0, next_game_tick_monotonic - asyncio.get_running_loop().time())
            await asyncio.sleep(sleep_seconds)

            next_game_tick_monotonic += GAME_TICK_INTERVAL_SECONDS

            for entity in list(shared_world_entities.values()):
                if not getattr(entity, "is_alive", False):
                    continue
                process_entity_game_hour_tick(entity)

            process_world_item_game_hour_tick()
            repopulate_game_hour_zones()

    except asyncio.CancelledError:
        raise


async def combat_round_loop() -> None:
    global next_npc_wander_monotonic
    try:
        while True:
            await asyncio.sleep(0.05)
            process_pending_auto_aggro()
            now = asyncio.get_running_loop().time()

            if next_npc_wander_monotonic is None:
                next_npc_wander_monotonic = now + COMBAT_ROUND_INTERVAL_SECONDS
            elif now >= next_npc_wander_monotonic:
                next_npc_wander_monotonic = now + COMBAT_ROUND_INTERVAL_SECONDS
                await _process_npc_wandering()

            combat_sessions: list[ClientSession] = []
            seen_sessions: set[str] = set()

            for session in active_character_sessions.values():
                session_key = session.player_state_key.strip().lower() or session.client_id
                if not session_key or session_key in seen_sessions:
                    continue
                seen_sessions.add(session_key)

                if session.disconnected_by_server or not session.is_authenticated:
                    continue
                if not session.combat.engaged_entity_ids:
                    continue
                combat_sessions.append(session)

            for session in connected_clients.values():
                session_key = session.player_state_key.strip().lower() or session.client_id
                if not session_key or session_key in seen_sessions:
                    continue
                seen_sessions.add(session_key)

                if not session.is_connected or session.disconnected_by_server or not session.is_authenticated:
                    continue
                if not session.combat.engaged_entity_ids:
                    continue
                combat_sessions.append(session)

            combat_rooms: dict[str, list[ClientSession]] = {}
            for session in combat_sessions:
                room_id = session.player.current_room_id
                if not room_id:
                    continue
                combat_rooms.setdefault(room_id, []).append(session)

            due_combat_rooms: dict[str, list[ClientSession]] = {}
            for room_id, room_sessions in combat_rooms.items():
                is_room_due = any(
                    sess.combat.next_round_monotonic is None
                    or now >= float(sess.combat.next_round_monotonic)
                    for sess in room_sessions
                )
                if is_room_due:
                    due_combat_rooms[room_id] = room_sessions

            combat_session_ids = {s.client_id for s in combat_sessions}
            for session in list(connected_clients.values()):
                if session.client_id in combat_session_ids:
                    continue
                if not session.is_authenticated or session.disconnected_by_server:
                    continue
                tick_out_of_combat_cooldowns(session)

            for room_id, room_sessions in due_combat_rooms.items():
                round_results: list[RoomRoundResult] = []
                room_sessions.sort(key=lambda s: (s.authenticated_character_name or "", s.client_id))

                entity_active_target_session: dict[str, str] = {}
                for actor_session in room_sessions:
                    engaged_entities = get_engaged_entities(actor_session)
                    if not engaged_entities:
                        continue
                    actor_target_key = get_session_combatant_key(actor_session)
                    for engaged_entity in engaged_entities:
                        target_key = sync_entity_target_player(engaged_entity)
                        if target_key == actor_target_key:
                            entity_active_target_session[engaged_entity.entity_id] = actor_session.client_id

                for actor_session in room_sessions:
                    allowed_entity_retaliation_ids = {
                        entity_id
                        for entity_id, target_session_id in entity_active_target_session.items()
                        if target_session_id == actor_session.client_id
                    }

                    combat_result = resolve_combat_round(
                        actor_session,
                        allowed_entity_retaliation_ids=allowed_entity_retaliation_ids,
                    )
                    if combat_result is not None:
                        round_results.append((actor_session, combat_result))

                if not round_results:
                    continue

                room_recipients = [
                    session
                    for session in connected_clients.values()
                    if session.is_connected
                    and not session.disconnected_by_server
                    and session.is_authenticated
                    and session.player.current_room_id == room_id
                ]

                for recipient in room_recipients:
                    skip_prompt = any(
                        actor_session == recipient and actor_session.pending_death_logout
                        for actor_session, _ in round_results
                    )
                    unified_display = _build_unified_room_round_display(recipient, round_results)
                    if unified_display is None:
                        continue
                    outbounds = [unified_display]
                    if not skip_prompt:
                        outbounds.append(display_force_prompt(recipient))
                    outbounds = _inject_private_lines_into_outbound(recipient, outbounds)
                    await send_outbound(recipient.websocket, outbounds)

                for actor_session, _ in round_results:
                    if not actor_session.pending_death_logout:
                        continue
                    reset_session_to_login(actor_session)
                    if actor_session.is_connected:
                        await send_outbound(actor_session.websocket, initial_auth_prompt(actor_session))

    except asyncio.CancelledError:
        raise
