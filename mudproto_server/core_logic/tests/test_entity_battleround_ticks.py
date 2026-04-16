import combat_ability_effects
from combat_ability_effects import process_entity_battle_round_tick, process_entity_game_hour_tick
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


def test_entity_game_hour_tick_applies_passive_regeneration() -> None:
    entity = _make_entity("entity-wounded", "Wounded Scout")
    entity.hit_points = 50
    entity.max_hit_points = 100
    entity.vigor = 4
    entity.max_vigor = 20
    entity.mana = 3
    entity.max_mana = 20

    process_entity_game_hour_tick(entity)

    assert entity.hit_points > 50
    assert entity.vigor > 4
    assert entity.mana > 3


def test_entity_game_hour_tick_uses_self_heal_spell_when_injured(monkeypatch) -> None:
    entity = _make_entity("entity-cleric", "Cleric")
    entity.hit_points = 40
    entity.max_hit_points = 100
    entity.mana = 50
    entity.max_mana = 50
    entity.spell_ids = ["spell.healing-light"]
    entity.spell_use_chance = 1.0

    monkeypatch.setattr(combat_ability_effects.random, "random", lambda: 0.0)
    monkeypatch.setattr(combat_ability_effects.random, "choice", lambda options: options[0])
    monkeypatch.setattr(combat_ability_effects, "get_spell_by_id", lambda _spell_id: {
        "spell_id": "spell.healing-light",
        "name": "Healing Light",
        "spell_type": "support",
        "cast_type": "self",
        "mana_cost": 10,
        "support_effect": "heal",
        "support_amount": 12,
        "support_dice_count": 0,
        "support_mode": "instant",
        "support_context": "Warm light closes old wounds.",
    })

    process_entity_game_hour_tick(entity)

    assert entity.hit_points > 40
    assert entity.mana == 40


def test_entity_game_hour_tick_restocks_limited_merchant_stock_after_configured_hours() -> None:
    entity = _make_entity("merchant-quartermaster", "Quartermaster Vessa")
    entity.is_merchant = True
    entity.merchant_restock_game_hours = 2
    entity.merchant_inventory = [
        {
            "template_id": "item.potion.mending",
            "infinite": False,
            "quantity": 0,
            "base_quantity": 3,
        },
        {
            "template_id": "weapon.training-sword",
            "infinite": True,
            "quantity": 1,
            "base_quantity": 1,
        },
    ]

    process_entity_game_hour_tick(entity)
    assert entity.merchant_inventory[0]["quantity"] == 0

    process_entity_game_hour_tick(entity)
    assert entity.merchant_inventory[0]["quantity"] == 3
