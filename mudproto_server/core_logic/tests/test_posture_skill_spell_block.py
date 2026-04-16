import combat_player_abilities as player_abilities
from models import ClientSession, EntityState


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


def test_player_sitting_cannot_use_skill() -> None:
    session = _make_session("client-sit-skill", "Lucia")
    session.is_sitting = True

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

    response, applied = player_abilities.use_skill(session, skill, "Goblin")

    assert applied is False
    assert "cannot use skills or spells" in _extract_display_text(response)


def test_player_resting_cannot_cast_spell() -> None:
    session = _make_session("client-rest-spell", "Lucia")
    session.is_resting = True

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

    response, applied = player_abilities.cast_spell(session, spell, "Goblin")

    assert applied is False
    assert "cannot use skills or spells" in _extract_display_text(response)


def test_player_sleeping_cannot_use_skill() -> None:
    session = _make_session("client-sleep-skill", "Lucia")
    session.is_sleeping = True

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

    response, applied = player_abilities.use_skill(session, skill, "Goblin")

    assert applied is False
    assert "Shhh... You are asleep. Use wake first." in _extract_display_text(response)


def test_player_sleeping_cannot_cast_spell() -> None:
    session = _make_session("client-sleep-spell", "Lucia")
    session.is_sleeping = True

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

    response, applied = player_abilities.cast_spell(session, spell, "Goblin")

    assert applied is False
    assert "Shhh... You are asleep. Use wake first." in _extract_display_text(response)


def test_player_damage_skill_on_peaceful_target_shows_peace_warning() -> None:
    session = _make_session("client-peace-skill", "Lucia")
    target = EntityState(
        entity_id="entity-milekeeper",
        name="Marra the Milekeeper",
        room_id="start",
        hit_points=100,
        max_hit_points=100,
        is_peaceful=True,
    )
    session.entities[target.entity_id] = target
    starting_vigor = session.status.vigor

    skill = {
        "skill_id": "skill.bash",
        "name": "Bash",
        "skill_type": "damage",
        "cast_type": "target",
        "vigor_cost": 10,
        "usable_out_of_combat": True,
        "damage_dice_count": 1,
        "damage_dice_sides": 1,
        "damage_modifier": 0,
    }

    response, applied = player_abilities.use_skill(session, skill, "Marra the Milekeeper")

    assert applied is False
    assert "Relax." in _extract_display_text(response)
    assert "Marra the Milekeeper is peaceful." in _extract_display_text(response)
    assert session.status.vigor == starting_vigor


def test_player_damage_spell_on_peaceful_target_shows_peace_warning() -> None:
    session = _make_session("client-peace-spell", "Lucia")
    target = EntityState(
        entity_id="entity-milekeeper",
        name="Marra the Milekeeper",
        room_id="start",
        hit_points=100,
        max_hit_points=100,
        is_peaceful=True,
    )
    session.entities[target.entity_id] = target
    starting_mana = session.status.mana

    spell = {
        "spell_id": "spell.missile",
        "name": "Magic Missile",
        "spell_type": "damage",
        "cast_type": "target",
        "mana_cost": 5,
        "damage_dice_count": 1,
        "damage_dice_sides": 1,
        "damage_modifier": 0,
    }

    response, applied = player_abilities.cast_spell(session, spell, "Marra the Milekeeper")

    assert applied is False
    assert "Relax." in _extract_display_text(response)
    assert "Marra the Milekeeper is peaceful." in _extract_display_text(response)
    assert session.status.mana == starting_mana
