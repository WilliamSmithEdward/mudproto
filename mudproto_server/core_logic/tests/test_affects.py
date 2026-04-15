import combat_player_abilities as player_abilities
import combat_ability_effects
import display_feedback
import game_hour_ticks
import item_logic
import json
from pathlib import Path
import pytest
from attribute_config import get_affect_template_by_id
from assets import _resolve_asset_affects, get_skill_by_id
from combat_ability_effects import _preview_entity_damage_with_reduction
from game_hour_ticks import process_game_hour_tick
from models import ActiveAffectState, ClientSession, EntityState, ItemState


def _make_session(client_id: str, name: str) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    return session


def _read_raw_skill(skill_id: str) -> dict:
    skills_path = Path(__file__).resolve().parents[2] / "configuration" / "assets" / "skills.json"
    payload = json.loads(skills_path.read_text(encoding="utf-8"))
    return next(
        skill for skill in payload
        if str(skill.get("skill_id", "")).strip().lower() == skill_id.strip().lower()
    )


def test_pressure_point_asset_has_target_damage_vulnerability_affect() -> None:
    skill = get_skill_by_id("skill.pressure-point")

    assert isinstance(skill, dict)
    assert [
        str(affect_id).strip().lower()
        for affect_id in skill.get("affect_ids", [])
        if str(affect_id).strip()
    ] == ["affect.increase-received-damage"]
    assert "affects" not in skill

    pressure_point_affect = get_affect_template_by_id("affect.increase-received-damage")
    assert isinstance(pressure_point_affect, dict)
    assert pressure_point_affect.get("affect_type") == "damage_received_multiplier"
    assert pressure_point_affect.get("target") == "target"
    assert pressure_point_affect.get("name") == "Pressure Point"
    assert pressure_point_affect.get("duration_rounds") == 3
    assert pressure_point_affect.get("damage_elements") == ["physical"]


def test_asset_loader_rejects_inline_affects_payloads() -> None:
    with pytest.raises(ValueError, match="inline affects are no longer supported"):
        _resolve_asset_affects(
            affect_ids=["affect.increase-received-damage"],
            affects=[{"affect_id": "affect.legacy-inline"}],
            context="Skill asset 'skill.test-inline'",
            configured_attribute_ids={"dex", "wis", "int", "str", "con"},
        )


def test_asset_loader_rejects_affect_override_objects() -> None:
    with pytest.raises(ValueError, match="affect_ids entries must be strings"):
        _resolve_asset_affects(
            affect_ids=[
                {
                    "affect_id": "affect.increase-received-damage",
                    "name": "Pressure Point",
                    "amount": 1.2,
                }
            ],
            affects=[],
            context="Skill asset 'skill.test-override'",
            configured_attribute_ids={"dex", "wis", "int", "str", "con"},
        )


def test_damage_received_multiplier_can_be_element_scoped() -> None:
    target = EntityState(
        entity_id="entity-goblin",
        name="Goblin",
        room_id="start",
        hit_points=200,
        max_hit_points=200,
    )
    target.active_affects.append(ActiveAffectState(
        affect_id="affect.increase-received-damage",
        affect_name="Pressure Point",
        affect_mode="battle_rounds",
        affect_type="damage_received_multiplier",
        affect_damage_elements=["physical"],
        affect_amount=1.2,
        remaining_rounds=2,
    ))

    assert _preview_entity_damage_with_reduction(target, 10, damage_element="physical") == 12
    assert _preview_entity_damage_with_reduction(target, 10, damage_element="storm") == 10


def test_damage_received_multiplier_without_elements_affects_all_damage() -> None:
    target = EntityState(
        entity_id="entity-ogre",
        name="Ogre",
        room_id="start",
        hit_points=200,
        max_hit_points=200,
    )
    target.active_affects.append(ActiveAffectState(
        affect_id="affect.increase-received-damage",
        affect_name="Expose",
        affect_mode="battle_rounds",
        affect_type="damage_received_multiplier",
        affect_damage_elements=[],
        affect_amount=1.3,
        remaining_rounds=2,
    ))

    assert _preview_entity_damage_with_reduction(target, 10, damage_element="physical") == 13
    assert _preview_entity_damage_with_reduction(target, 10, damage_element="fire") == 13


def test_pressure_point_applies_damage_received_multiplier_to_target(monkeypatch) -> None:
    session = _make_session("client-pressure", "Lucia")
    target = EntityState(
        entity_id="entity-goblin",
        name="Goblin",
        room_id="start",
        hit_points=200,
        max_hit_points=200,
    )
    session.entities[target.entity_id] = target

    session.player.attributes["dex"] = 10
    skill = {
        "skill_id": "skill.pressure-point",
        "name": "Pressure Point",
        "skill_type": "damage",
        "cast_type": "target",
        "vigor_cost": 1,
        "usable_out_of_combat": False,
        "scaling_attribute_id": "",
        "scaling_multiplier": 0.0,
        "level_scaling_multiplier": 0.0,
        "damage_context": "[a/an] [verb] struck.",
        "damage_dice_count": 1,
        "damage_dice_sides": 1,
        "damage_modifier": 0,
        "affect_ids": ["affect.increase-received-damage"],
    }

    monkeypatch.setattr(player_abilities, "roll_skill_damage", lambda _skill: 1)
    monkeypatch.setattr(display_feedback, "display_command_result", lambda *_args, **_kwargs: {})

    _, applied = player_abilities.use_skill(session, skill, "Goblin")

    assert applied is True
    assert len(target.active_affects) == 1
    assert target.active_affects[0].affect_type == "damage_received_multiplier"

    preview_damage = _preview_entity_damage_with_reduction(target, 10)
    assert preview_damage == 12


def test_item_affect_can_store_dice_payload(monkeypatch) -> None:
    session = _make_session("client-affect-item", "Lucia")
    item = ItemState(item_id="item-regen", name="Regeneration Tonic", equippable=False)

    session.inventory_items[item.item_id] = item

    template = {
        "name": "Regeneration Tonic",
        "effect_type": "",
        "effect_target": "",
        "effect_amount": 0,
        "use_lag_seconds": 0,
        "affect_ids": ["affect.regeneration"],
    }

    monkeypatch.setattr(item_logic, "_resolve_misc_inventory_selector", lambda _session, _selector: (item, None))
    monkeypatch.setattr(item_logic, "_find_item_template_for_misc_item", lambda _item: template)
    monkeypatch.setattr(item_logic, "display_command_result", lambda *_args, **_kwargs: {})

    result = item_logic._use_misc_item(session, "regeneration tonic")

    assert isinstance(result, dict)
    assert len(session.active_affects) == 1
    assert session.active_affects[0].affect_dice_count == 1
    assert session.active_affects[0].affect_dice_sides == 21


def test_timed_regeneration_affect_ticks_and_expires(monkeypatch) -> None:
    session = _make_session("client-regen", "Lucia")
    session.status.hit_points = 10
    before_hit_points = session.status.hit_points
    session.active_affects.append(ActiveAffectState(
        affect_id="affect.regen",
        affect_name="Regeneration",
        affect_mode="timed",
        affect_type="regeneration",
        target_resource="hit_points",
        affect_amount=0,
        affect_dice_count=1,
        affect_dice_sides=1,
        affect_roll_modifier=0,
        affect_scaling_bonus=0,
        remaining_hours=1,
        remaining_rounds=0,
    ))

    monkeypatch.setattr(game_hour_ticks, "get_player_resource_caps", lambda _session: {
        "hit_points": 100,
        "mana": 100,
        "vigor": 100,
    })
    monkeypatch.setattr(combat_ability_effects, "get_player_resource_caps", lambda _session: {
        "hit_points": 100,
        "mana": 100,
        "vigor": 100,
    })
    process_game_hour_tick(session)

    assert session.status.hit_points >= before_hit_points + 1
    assert session.active_affects == []


# ---------------------------------------------------------------------------
# Duration inheritance: affects inherit duration from parent ability
# ---------------------------------------------------------------------------


def test_affect_inherits_duration_rounds_from_parent_ability(monkeypatch) -> None:
    """When an affect template omits duration_rounds, it inherits from the parent ability."""
    from combat_ability_effects import _apply_ability_affects

    session = _make_session("client-inherit-dur", "Tester")
    ability = {
        "duration_rounds": 5,
        "affect_ids": ["affect.damage-reduction"],
    }
    monkeypatch.setattr(
        combat_ability_effects,
        "get_affect_template_by_id",
        lambda affect_id: {
            "affect_id": affect_id,
            "name": "Guard",
            "affect_type": "damage_reduction",
            "target": "self",
            "affect_mode": "battle_rounds",
            "amount": 3,
        },
    )

    _apply_ability_affects(actor=session, target=session, ability=ability, affect_target="self")

    assert len(session.active_affects) == 1
    assert session.active_affects[0].remaining_rounds == 5


def test_affect_inherits_duration_hours_from_parent_ability(monkeypatch) -> None:
    """When an affect template omits duration_hours, it inherits from the parent ability."""
    from combat_ability_effects import _apply_ability_affects

    session = _make_session("client-inherit-hours", "Tester")
    ability = {
        "duration_hours": 4,
        "affect_ids": ["affect.regeneration"],
    }
    monkeypatch.setattr(
        combat_ability_effects,
        "get_affect_template_by_id",
        lambda affect_id: {
            "affect_id": affect_id,
            "name": "Regeneration",
            "affect_type": "regeneration",
            "target": "self",
            "affect_mode": "timed",
            "target_resource": "hit_points",
            "amount": 5,
        },
    )

    _apply_ability_affects(actor=session, target=session, ability=ability, affect_target="self")

    assert len(session.active_affects) == 1
    assert session.active_affects[0].remaining_hours == 4


def test_affect_explicit_duration_overrides_parent(monkeypatch) -> None:
    """An affect template with its own duration_rounds takes priority over the parent's."""
    from combat_ability_effects import _apply_ability_affects

    session = _make_session("client-override-dur", "Tester")
    ability = {
        "duration_rounds": 5,
        "affect_ids": ["affect.damage-reduction"],
    }
    monkeypatch.setattr(
        combat_ability_effects,
        "get_affect_template_by_id",
        lambda affect_id: {
            "affect_id": affect_id,
            "name": "Guard",
            "affect_type": "damage_reduction",
            "target": "self",
            "affect_mode": "battle_rounds",
            "amount": 2,
            "duration_rounds": 7,
        },
    )

    _apply_ability_affects(actor=session, target=session, ability=ability, affect_target="self")

    assert len(session.active_affects) == 1
    assert session.active_affects[0].remaining_rounds == 7


# ---------------------------------------------------------------------------
# Battle-round tick ordering: affects last for the full N rounds
# ---------------------------------------------------------------------------


def test_battle_round_affect_active_for_full_duration() -> None:
    """An affect with duration_rounds=3 should be active during 3 attack phases."""
    from battle_round_ticks import process_player_battle_round_tick
    from combat_ability_effects import _is_affect_active

    session = _make_session("client-tick-dur", "Tester")
    session.active_affects.append(ActiveAffectState(
        affect_id="affect.damage-reduction",
        affect_name="Guard",
        affect_mode="battle_rounds",
        affect_type="damage_reduction",
        affect_amount=5,
        remaining_rounds=3,
    ))

    # Simulate 3 combat rounds: attacks happen first, then tick.
    for round_num in range(3):
        assert _is_affect_active(session.active_affects[0]), (
            f"Affect should be active during attack phase of round {round_num + 1}"
        )
        process_player_battle_round_tick(session)

    # After 3 ticks, the affect should be expired.
    assert session.active_affects == [], "Affect should expire after 3 rounds"


def test_battle_round_affect_not_consumed_before_attacks() -> None:
    """Verify the tick order: duration should still be full before the first tick."""
    session = _make_session("client-tick-order", "Tester")
    session.active_affects.append(ActiveAffectState(
        affect_id="affect.extra-hits",
        affect_name="Flurry",
        affect_mode="battle_rounds",
        affect_type="extra_hits",
        extra_unarmed_hits=2,
        remaining_rounds=3,
    ))

    # Before any tick, the affect has full duration.
    assert session.active_affects[0].remaining_rounds == 3
    # The combat round would run attacks here (affect is active).
    # Then tick:
    from battle_round_ticks import process_player_battle_round_tick
    process_player_battle_round_tick(session)
    assert session.active_affects[0].remaining_rounds == 2
    assert len(session.active_affects) == 1


# ---------------------------------------------------------------------------
# Asset-level: fist-flurry and centered-guard inherit duration from skill
# ---------------------------------------------------------------------------


def test_fist_flurry_affect_inherits_skill_duration() -> None:
    """Fist Flurry affect entry has no duration_rounds; it inherits from the skill."""
    from combat_ability_effects import _apply_ability_affects

    raw_skill = _read_raw_skill("skill.fist-flurry")
    raw_affects = raw_skill.get("affect_ids", [])
    assert len(raw_affects) >= 1
    assert "duration_rounds" not in raw_affects[0]

    skill = get_skill_by_id("skill.fist-flurry")
    assert isinstance(skill, dict)
    assert skill.get("duration_rounds") == 3
    assert "affects" not in skill

    # Verify runtime: applying the skill should produce an affect with duration 3.
    session = _make_session("client-flurry-inherit", "Tester")
    _apply_ability_affects(actor=session, target=session, ability=skill, affect_target="self")

    assert len(session.active_affects) == 1
    assert session.active_affects[0].remaining_rounds == 3


def test_centered_guard_affect_inherits_skill_duration() -> None:
    """Centered Guard affect entry has no duration_rounds; it inherits from the skill."""
    from combat_ability_effects import _apply_ability_affects

    raw_skill = _read_raw_skill("skill.centered-guard")
    raw_affects = raw_skill.get("affect_ids", [])
    assert len(raw_affects) >= 1
    assert "duration_rounds" not in raw_affects[0]

    skill = get_skill_by_id("skill.centered-guard")
    assert isinstance(skill, dict)
    assert skill.get("duration_rounds") == 3
    assert "affects" not in skill

    session = _make_session("client-guard-inherit", "Tester")
    _apply_ability_affects(actor=session, target=session, ability=skill, affect_target="self")

    assert len(session.active_affects) == 1
    assert session.active_affects[0].remaining_rounds == 3
