from combat_ability_effects import process_entity_battle_round_tick
from models import ActiveSupportEffectState, EntityState


def _make_entity(entity_id: str, name: str) -> EntityState:
    return EntityState(
        entity_id=entity_id,
        name=name,
        room_id="start",
        hit_points=50,
        max_hit_points=100,
    )


def test_entity_battleround_tick_decrements_skill_and_spell_cooldowns() -> None:
    entity = _make_entity("entity-scout", "Scout")
    entity.skill_cooldowns["skill.jab"] = 3
    entity.spell_cooldowns["spell.spark"] = 2

    process_entity_battle_round_tick(entity)

    assert entity.skill_cooldowns["skill.jab"] == 2
    assert entity.spell_cooldowns["spell.spark"] == 1


def test_entity_battleround_tick_applies_support_and_clears_expired() -> None:
    entity = _make_entity("entity-priest", "Priest")
    entity.hit_points = 50
    entity.active_support_effects.append(ActiveSupportEffectState(
        spell_id="spell.regen",
        spell_name="Regeneration",
        support_mode="battle_rounds",
        support_effect="heal",
        support_amount=5,
        remaining_hours=0,
        remaining_rounds=2,
    ))

    process_entity_battle_round_tick(entity)

    assert entity.hit_points == 55
    assert len(entity.active_support_effects) == 1
    assert entity.active_support_effects[0].remaining_rounds == 1

    process_entity_battle_round_tick(entity)

    assert entity.hit_points == 60
    assert len(entity.active_support_effects) == 0
