from combat import begin_attack, resolve_combat_round
from combat_state import get_engaged_entity, start_combat
from containers import handle_container_command
from display_feedback import display_error, display_force_prompt
from models import ClientSession
from room_actions import handle_room_keyword_action
from room_exits import handle_room_exit_command
from targeting_follow import _list_group_member_sessions, _resolve_room_player_selector
from world_population import spawn_dummy

from .movement import flee
from .types import OutboundResult


HandledResult = OutboundResult | None


def _assist_on_entity(
    session: ClientSession,
    *,
    assisted_session: ClientSession,
    target_entity,
) -> HandledResult:
    if target_entity is None or not getattr(target_entity, "is_alive", False):
        return display_error("That target is no longer a valid combat target.", session)

    started = start_combat(session, target_entity.entity_id, "player")
    if not started:
        return display_error(f"You fail to assist {assisted_session.authenticated_character_name or 'them'}.", session)

    immediate_round = resolve_combat_round(session)
    if immediate_round is not None:
        if session.pending_death_logout:
            return immediate_round
        return [immediate_round, display_force_prompt(session)]

    return display_error(f"You fail to engage {target_entity.name}.", session)


def handle_world_command(
    session: ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb == "spawn":
        target_name = " ".join(args).strip().lower()
        if target_name != "dummy":
            return display_error("Usage: spawn dummy", session)

        return spawn_dummy(session)

    if verb in {"attack", "ki", "kil", "kill"}:
        target_name = " ".join(args).strip()
        if not target_name:
            return display_error(f"Usage: {verb} <target>", session)

        if session.combat.engaged_entity_ids:
            return display_error("You're already fighting!", session)

        return begin_attack(session, target_name)

    if verb in {"assist", "ass", "assi", "assis"}:
        if session.combat.engaged_entity_ids:
            return display_error("You're already fighting!", session)

        selector_text = " ".join(args).strip()
        if selector_text:
            target_session, target_error = _resolve_room_player_selector(session, selector_text)
            if target_session is None:
                return display_error(target_error or f"No player named '{selector_text}' is here.", session)
            if target_session.client_id == session.client_id:
                return display_error("You cannot assist yourself.", session)

            target_entity = get_engaged_entity(target_session)
            if target_entity is None:
                target_name = (target_session.authenticated_character_name or "that player").strip() or "that player"
                return display_error(f"{target_name} is not engaged in combat.", session)

            return _assist_on_entity(session, assisted_session=target_session, target_entity=target_entity)

        _leader_session, group_sessions = _list_group_member_sessions(session)
        if len(group_sessions) <= 1:
            return display_error("You are not in a party. Usage: assist <player>", session)

        for group_member in group_sessions:
            if group_member.client_id == session.client_id:
                continue
            if group_member.player.current_room_id != session.player.current_room_id:
                continue

            target_entity = get_engaged_entity(group_member)
            if target_entity is None:
                continue

            return _assist_on_entity(session, assisted_session=group_member, target_entity=target_entity)

        return display_error("No valid party member in this room is engaged in combat.", session)

    if verb == "flee":
        return flee(session)

    room_exit_result = handle_room_exit_command(session, verb, args, _command_text)
    if room_exit_result is not None:
        return room_exit_result

    room_keyword_result = handle_room_keyword_action(session, _command_text)
    if room_keyword_result is not None:
        return room_keyword_result

    container_result = handle_container_command(session, verb, args, _command_text)
    if container_result is not None:
        return container_result

    return None
