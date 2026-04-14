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


def test_bash_applies_target_lag_to_entity(monkeypatch) -> None:
    session = _make_session("client-bash", "Lucia")
    target = EntityState(
        entity_id="entity-goblin",
        name="Goblin",
        room_id="start",
        hit_points=200,
        max_hit_points=200,
    )
    session.entities[target.entity_id] = target

    skill = {
        "skill_id": "skill.bash",
        "name": "Bash",
        "skill_type": "damage",
        "cast_type": "target",
        "vigor_cost": 10,
        "usable_out_of_combat": False,
        "damage_context": "[a/an] [verb] slammed.",
        "target_lag_rounds": 2,
        "target_posture": "sitting",
        "damage_dice_count": 1,
        "damage_dice_sides": 1,
        "damage_modifier": 0,
    }

    monkeypatch.setattr(player_abilities, "roll_skill_damage", lambda _skill: 15)

    response, applied = player_abilities.use_skill(session, skill, "Goblin")

    assert isinstance(response, dict)
    assert applied is True
    assert target.skill_lag_rounds_remaining == 2
    assert target.is_sitting is True
