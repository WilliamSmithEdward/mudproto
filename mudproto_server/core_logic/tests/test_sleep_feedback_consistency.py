import command_handlers.movement as movement
from command_handlers.observation import handle_observation_command
from combat_player_abilities import cast_spell, use_skill
from models import ClientSession


_ASLEEP_FEEDBACK = "Shhh... You are asleep. Use wake first."


def _make_session(client_id: str, name: str) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    return session


def _extract_display_text(outbound: dict | list[dict]) -> str:
    messages = outbound if isinstance(outbound, list) else [outbound]
    lines: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("type") != "display":
            continue
        payload = message.get("payload")
        if not isinstance(payload, dict):
            continue
        raw_lines = payload.get("lines", [])
        if not isinstance(raw_lines, list):
            continue
        for line in raw_lines:
            if not isinstance(line, list):
                continue
            lines.append("".join(str(part.get("text", "")) for part in line if isinstance(part, dict)))
    return "\n".join(lines)


def test_sleep_block_feedback_is_consistent_across_handlers() -> None:
    session = _make_session("client-sleep-feedback", "Lucia")
    session.is_sleeping = True

    move_outbound = movement.try_move(session, "north")
    assert isinstance(move_outbound, dict)
    assert _ASLEEP_FEEDBACK in _extract_display_text(move_outbound)

    look_outbound = handle_observation_command(session, "look", [], "look")
    assert isinstance(look_outbound, dict)
    assert _ASLEEP_FEEDBACK in _extract_display_text(look_outbound)

    skill = {
        "skill_id": "skill.jab",
        "name": "Jab",
        "skill_type": "damage",
        "cast_type": "target",
        "vigor_cost": 1,
        "usable_out_of_combat": True,
        "damage_dice_count": 1,
        "damage_dice_sides": 1,
        "damage_modifier": 0,
    }
    skill_outbound, skill_applied = use_skill(session, skill, "Goblin")
    assert skill_applied is False
    assert _ASLEEP_FEEDBACK in _extract_display_text(skill_outbound)

    spell = {
        "spell_id": "spell.missile",
        "name": "Magic Missile",
        "spell_type": "damage",
        "cast_type": "target",
        "mana_cost": 1,
        "damage_dice_count": 1,
        "damage_dice_sides": 1,
        "damage_modifier": 0,
    }
    spell_outbound, spell_applied = cast_spell(session, spell, "Goblin")
    assert spell_applied is False
    assert _ASLEEP_FEEDBACK in _extract_display_text(spell_outbound)
