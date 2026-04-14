import asyncio

import combat
import combat_ability_effects as effects
import game_hour_ticks
import server_loops
from command_handlers.posture import handle_posture_command
from models import ClientSession, EntityState
from session_registry import shared_world_entities


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


def _make_session(client_id: str, name: str) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    return session


def test_posture_commands_toggle_sitting_state() -> None:
    session = _make_session("client-posture", "Lucia")

    sit_outbound = handle_posture_command(session, "sit", [], "sit")
    assert session.is_sitting is True
    assert isinstance(sit_outbound, dict)
    assert "You sit down." in _extract_display_text(sit_outbound)

    stand_outbound = handle_posture_command(session, "stand", [], "stand")
    assert session.is_sitting is False
    assert session.is_resting is False
    assert isinstance(stand_outbound, dict)
    assert "You stand up." in _extract_display_text(stand_outbound)


def test_posture_command_aliases_work() -> None:
    session = _make_session("client-aliases", "Lucia")

    for sit_alias in ["si", "sit"]:
        session.is_sitting = False
        session.is_resting = True
        outbound = handle_posture_command(session, sit_alias, [], sit_alias)
        assert session.is_sitting is True
        assert session.is_resting is False
        assert isinstance(outbound, dict)

    for rest_alias in ["r", "re", "res", "rest"]:
        session.is_sitting = True
        session.is_resting = False
        outbound = handle_posture_command(session, rest_alias, [], rest_alias)
        assert session.is_resting is True
        assert session.is_sitting is False
        assert isinstance(outbound, dict)

    for stand_alias in ["st", "sta", "stan", "stand"]:
        session.is_sitting = False
        session.is_resting = True
        outbound = handle_posture_command(session, stand_alias, [], stand_alias)
        assert session.is_sitting is False
        assert session.is_resting is False
        assert isinstance(outbound, dict)


def test_sitting_damage_multiplier_applies_to_player(monkeypatch) -> None:
    session = _make_session("client-player", "Lucia")
    session.status.hit_points = 100
    session.is_sitting = True

    monkeypatch.setattr(
        effects,
        "get_posture_damage_multiplier",
        lambda posture_state: 1.5 if posture_state == "sitting" else 1.0,
    )

    dealt = effects._apply_player_damage_with_reduction(session, 10)

    assert dealt == 15
    assert session.status.hit_points == 85


def test_sitting_damage_multiplier_applies_to_entity(monkeypatch) -> None:
    entity = EntityState(
        entity_id="entity-ogre",
        name="Ogre",
        room_id="start",
        hit_points=100,
        max_hit_points=100,
    )
    entity.is_sitting = True

    monkeypatch.setattr(
        effects,
        "get_posture_damage_multiplier",
        lambda posture_state: 1.5 if posture_state == "sitting" else 1.0,
    )

    dealt = effects._apply_entity_damage_with_reduction(entity, 10)

    assert dealt == 15
    assert entity.hit_points == 85


def test_resting_damage_multiplier_applies_to_player(monkeypatch) -> None:
    session = _make_session("client-rest-player", "Lucia")
    session.status.hit_points = 100
    session.is_resting = True

    monkeypatch.setattr(
        effects,
        "get_posture_damage_multiplier",
        lambda posture_state: 1.25 if posture_state == "resting" else 1.0,
    )

    dealt = effects._apply_player_damage_with_reduction(session, 20)

    assert dealt == 25
    assert session.status.hit_points == 75


def test_resting_regeneration_bonus_multiplier_applies(monkeypatch) -> None:
    session = _make_session("client-rest-regen", "Lucia")
    session.is_resting = True
    session.status.hit_points = 10
    session.status.vigor = 10
    session.status.mana = 10

    monkeypatch.setattr(game_hour_ticks, "get_player_resource_caps", lambda _session: {
        "hit_points": 100,
        "vigor": 100,
        "mana": 100,
    })
    monkeypatch.setattr(game_hour_ticks, "load_regeneration_config", lambda: {
        "resources": {
            "hit_points": {
                "attribute_id": "con",
                "min_amount": 1,
                "percent_by_attribute": [{"min": 0, "percent": 0.1}],
            },
            "vigor": {
                "attribute_id": "dex",
                "min_amount": 1,
                "percent_by_attribute": [{"min": 0, "percent": 0.1}],
            },
            "mana": {
                "attribute_id": "wis",
                "min_amount": 1,
                "percent_by_attribute": [{"min": 0, "percent": 0.1}],
            },
        },
    })
    monkeypatch.setattr(game_hour_ticks, "get_posture_regeneration_bonus_multiplier", lambda _state: 1.5)

    game_hour_ticks.process_game_hour_tick(session)

    assert session.status.hit_points == 25
    assert session.status.vigor == 25
    assert session.status.mana == 25


def test_wandering_loop_stands_sitting_npc_when_not_lagged(monkeypatch) -> None:
    entity = EntityState(
        entity_id="entity-bandit",
        name="Bandit",
        room_id="start",
        hit_points=100,
        max_hit_points=100,
    )
    entity.is_sitting = True
    entity.skill_lag_rounds_remaining = 0
    entity.spell_lag_rounds_remaining = 0

    shared_world_entities.clear()
    shared_world_entities[entity.entity_id] = entity

    monkeypatch.setattr(server_loops, "_iter_room_sessions", lambda _room_id: [])

    async def _fake_send_outbound(_websocket, _outbound):
        return True

    monkeypatch.setattr(server_loops, "send_outbound", _fake_send_outbound)

    try:
        asyncio.run(server_loops._process_npc_wandering())
        assert entity.is_sitting is False
    finally:
        shared_world_entities.clear()


def test_combat_round_stands_sitting_npc_when_not_lagged(monkeypatch) -> None:
    session = _make_session("client-combat", "Lucia")
    entity = EntityState(
        entity_id="entity-bandit",
        name="Bandit",
        room_id="start",
        hit_points=100,
        max_hit_points=100,
    )
    entity.is_sitting = True
    entity.skill_lag_rounds_remaining = 0
    entity.spell_lag_rounds_remaining = 0

    monkeypatch.setattr(combat, "_entity_try_cast_spell", lambda _session, _entity, _parts: False)
    monkeypatch.setattr(combat, "_entity_try_use_skill", lambda _session, _entity, _parts: False)
    monkeypatch.setattr(combat, "roll_hit", lambda _hit_mod, _armor_class: False)

    parts: list[dict] = []
    combat._apply_entity_attacks(session, entity, parts, allow_off_hand=False)

    rendered = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
    assert entity.is_sitting is False
    assert "stands up." in rendered


def test_combat_round_does_not_stand_sitting_npc_while_lagged(monkeypatch) -> None:
    session = _make_session("client-combat-lagged", "Lucia")
    entity = EntityState(
        entity_id="entity-bandit",
        name="Bandit",
        room_id="start",
        hit_points=100,
        max_hit_points=100,
    )
    entity.is_sitting = True
    entity.skill_lag_rounds_remaining = 1
    entity.spell_lag_rounds_remaining = 0

    monkeypatch.setattr(combat, "_entity_try_cast_spell", lambda _session, _entity, _parts: False)
    monkeypatch.setattr(combat, "_entity_try_use_skill", lambda _session, _entity, _parts: False)
    monkeypatch.setattr(combat, "roll_hit", lambda _hit_mod, _armor_class: False)

    parts: list[dict] = []
    combat._apply_entity_attacks(session, entity, parts, allow_off_hand=False)

    rendered = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
    assert entity.is_sitting is True
    assert entity.skill_lag_rounds_remaining == 0
    assert "stands up." not in rendered
