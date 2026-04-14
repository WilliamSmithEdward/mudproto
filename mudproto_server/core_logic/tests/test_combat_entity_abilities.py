import combat_entity_abilities as entity_abilities
from models import ActiveSupportEffectState, ClientSession, EntityState


def _make_session(client_id: str, name: str) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    return session


def _make_entity(entity_id: str, name: str) -> EntityState:
    return EntityState(
        entity_id=entity_id,
        name=name,
        room_id="start",
        hit_points=200,
        max_hit_points=200,
    )


def test_entity_does_not_recast_active_timed_support_spell(monkeypatch) -> None:
    session = _make_session("client-player", "Lucia")
    entity = _make_entity("entity-priest", "Priest")
    entity.spell_ids = ["spell.regeneration-ward"]
    entity.spell_use_chance = 1.0
    entity.mana = 100
    entity.active_support_effects.append(ActiveSupportEffectState(
        spell_id="spell.regeneration-ward",
        spell_name="Regeneration Ward",
        support_mode="timed",
        support_effect="heal",
        support_amount=10,
        remaining_hours=2,
    ))

    monkeypatch.setattr(entity_abilities.random, "random", lambda: 0.0)
    monkeypatch.setattr(entity_abilities, "get_spell_by_id", lambda _spell_id: {
        "spell_id": "spell.regeneration-ward",
        "name": "Regeneration Ward",
        "spell_type": "support",
        "cast_type": "self",
        "mana_cost": 10,
        "support_effect": "heal",
        "support_amount": 10,
        "support_mode": "timed",
        "duration_hours": 2,
        "duration_rounds": 0,
        "support_context": "A warm light surrounds the caster.",
    })

    parts: list[dict] = []
    casted = entity_abilities._entity_try_cast_spell(session, entity, parts)

    assert casted is False
    assert entity.mana == 100
    assert parts == []


def test_entity_does_not_recast_active_round_support_skill(monkeypatch) -> None:
    session = _make_session("client-player", "Lucia")
    entity = _make_entity("entity-monk", "Monk")
    entity.skill_ids = ["skill.centered-guard"]
    entity.skill_use_chance = 1.0
    entity.vigor = 100
    entity.active_support_effects.append(ActiveSupportEffectState(
        spell_id="skill.centered-guard",
        spell_name="Centered Guard",
        support_mode="battle_rounds",
        support_effect="damage_reduction",
        support_amount=2,
        remaining_hours=0,
        remaining_rounds=2,
    ))

    monkeypatch.setattr(entity_abilities.random, "random", lambda: 0.0)
    monkeypatch.setattr(entity_abilities, "get_skill_by_id", lambda _skill_id: {
        "skill_id": "skill.centered-guard",
        "name": "Centered Guard",
        "skill_type": "support",
        "cast_type": "self",
        "vigor_cost": 8,
        "support_effect": "damage_reduction",
        "support_amount": 2,
        "support_mode": "battle_rounds",
        "duration_hours": 0,
        "duration_rounds": 3,
        "support_context": "A calm stance absorbs incoming force.",
    })

    parts: list[dict] = []
    used = entity_abilities._entity_try_use_skill(session, entity, parts)

    assert used is False
    assert entity.vigor == 100
    assert parts == []
