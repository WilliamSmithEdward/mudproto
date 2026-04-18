import combat_entity_abilities as entity_abilities
from models import ActiveAffectState, ClientSession, EntityState


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
    entity.active_affects.append(ActiveAffectState(
        affect_id="affect.regeneration",
        affect_name="Regeneration Ward",
        affect_mode="timed",
        affect_type="regeneration",
        target_resource="hit_points",
        affect_amount=10,
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
    entity.active_affects.append(ActiveAffectState(
        affect_id="affect.damage-reduction",
        affect_name="Centered Guard",
        affect_mode="battle_rounds",
        affect_type="damage_reduction",
        affect_amount=2,
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


def test_entity_target_lag_skill_sets_player_sitting(monkeypatch) -> None:
    session = _make_session("client-player", "Lucia")
    entity = _make_entity("entity-ogre", "Ogre")
    entity.skill_ids = ["skill.shield-bash"]
    entity.skill_use_chance = 1.0
    entity.vigor = 100

    monkeypatch.setattr(entity_abilities.random, "random", lambda: 0.0)
    monkeypatch.setattr(entity_abilities.random, "choice", lambda options: options[0])
    monkeypatch.setattr(entity_abilities, "roll_skill_damage", lambda _skill: 12)
    monkeypatch.setattr(entity_abilities, "apply_lag", lambda _session, _seconds: None)
    monkeypatch.setattr(entity_abilities, "get_skill_by_id", lambda _skill_id: {
        "skill_id": "skill.shield-bash",
        "name": "Shield Bash",
        "skill_type": "damage",
        "cast_type": "target",
        "vigor_cost": 10,
        "target_lag_rounds": 2,
        "target_posture": "sitting",
        "damage_dice_count": 1,
        "damage_dice_sides": 1,
        "damage_modifier": 0,
    })

    parts: list[dict] = []
    used = entity_abilities._entity_try_use_skill(session, entity, parts)

    assert used is True
    assert session.is_sitting is True
    assert entity.skill_lag_rounds_remaining == 2


def test_entity_sitting_does_not_use_skill(monkeypatch) -> None:
    session = _make_session("client-player", "Lucia")
    entity = _make_entity("entity-ogre", "Ogre")
    entity.is_sitting = True
    entity.skill_ids = ["skill.shield-bash"]
    entity.skill_use_chance = 1.0
    entity.vigor = 100

    monkeypatch.setattr(entity_abilities.random, "random", lambda: 0.0)
    monkeypatch.setattr(entity_abilities, "get_skill_by_id", lambda _skill_id: {
        "skill_id": "skill.shield-bash",
        "name": "Shield Bash",
        "skill_type": "damage",
        "cast_type": "target",
        "vigor_cost": 10,
        "damage_dice_count": 1,
        "damage_dice_sides": 1,
        "damage_modifier": 0,
    })

    parts: list[dict] = []
    used = entity_abilities._entity_try_use_skill(session, entity, parts)

    assert used is False
    assert entity.vigor == 100
    assert parts == []


def test_entity_named_skill_message_uses_name_without_article_when_flag_is_true(monkeypatch) -> None:
    session = _make_session("client-player", "Lucia")
    entity = _make_entity("entity-seln", "Seln of the Pins")
    entity.is_named = True
    entity.skill_ids = ["skill.gutter-step"]
    entity.skill_use_chance = 1.0
    entity.vigor = 100

    monkeypatch.setattr(entity_abilities.random, "random", lambda: 0.0)
    monkeypatch.setattr(entity_abilities.random, "choice", lambda options: options[0])
    monkeypatch.setattr(entity_abilities, "roll_skill_damage", lambda _skill: 12)
    monkeypatch.setattr(entity_abilities, "apply_lag", lambda _session, _seconds: None)
    monkeypatch.setattr(entity_abilities, "get_skill_by_id", lambda _skill_id: {
        "skill_id": "skill.gutter-step",
        "name": "Gutter Step",
        "skill_type": "damage",
        "cast_type": "target",
        "vigor_cost": 10,
        "description": "A quick slip across broken footing followed by a low killing strike.",
        "damage_dice_count": 1,
        "damage_dice_sides": 1,
        "damage_modifier": 0,
    })

    parts: list[dict] = []
    used = entity_abilities._entity_try_use_skill(session, entity, parts)

    rendered = "".join(str(part.get("text", "")) for part in parts)
    assert used is True
    assert "Seln of the Pins uses Gutter Step on you!" in rendered
    assert "A Seln of the Pins uses Gutter Step on you!" not in rendered


def test_entity_damage_skill_does_not_echo_player_perspective_context_to_victim(monkeypatch) -> None:
    session = _make_session("client-player", "Lucia")
    entity = _make_entity("entity-knifeman", "Crowbanner Knifeman")
    entity.skill_ids = ["skill.crippling-pitchknife"]
    entity.skill_use_chance = 1.0
    entity.vigor = 100

    monkeypatch.setattr(entity_abilities.random, "random", lambda: 0.0)
    monkeypatch.setattr(entity_abilities.random, "choice", lambda options: options[0])
    monkeypatch.setattr(entity_abilities, "roll_skill_damage", lambda _skill: 12)
    monkeypatch.setattr(entity_abilities, "apply_lag", lambda _session, _seconds: None)
    monkeypatch.setattr(entity_abilities, "get_skill_by_id", lambda _skill_id: {
        "skill_id": "skill.crippling-pitchknife",
        "name": "Crippling Pitchknife",
        "skill_type": "damage",
        "cast_type": "target",
        "vigor_cost": 10,
        "description": "A sudden thrust or thrown knife that leaves the target fighting for balance.",
        "damage_context": "You drive a crippling pitchknife into your foe!",
        "damage_dice_count": 1,
        "damage_dice_sides": 1,
        "damage_modifier": 0,
    })

    parts: list[dict] = []
    used = entity_abilities._entity_try_use_skill(session, entity, parts)

    rendered = "".join(str(part.get("text", "")) for part in parts)
    assert used is True
    assert "You drive a crippling pitchknife into your foe!" not in rendered
    assert "You are hit by Crippling Pitchknife." in rendered


def test_entity_resting_does_not_cast_spell(monkeypatch) -> None:
    session = _make_session("client-player", "Lucia")
    entity = _make_entity("entity-priest", "Priest")
    entity.is_resting = True
    entity.spell_ids = ["spell.arcane-bolt"]
    entity.spell_use_chance = 1.0
    entity.mana = 100

    monkeypatch.setattr(entity_abilities.random, "random", lambda: 0.0)
    monkeypatch.setattr(entity_abilities, "get_spell_by_id", lambda _spell_id: {
        "spell_id": "spell.arcane-bolt",
        "name": "Arcane Bolt",
        "spell_type": "damage",
        "cast_type": "target",
        "mana_cost": 10,
        "damage_dice_count": 1,
        "damage_dice_sides": 1,
        "damage_modifier": 0,
    })

    parts: list[dict] = []
    casted = entity_abilities._entity_try_cast_spell(session, entity, parts)

    assert casted is False
    assert entity.mana == 100
    assert parts == []


def test_entity_sleeping_does_not_use_skill(monkeypatch) -> None:
    session = _make_session("client-player", "Lucia")
    entity = _make_entity("entity-ogre", "Ogre")
    entity.is_sleeping = True
    entity.skill_ids = ["skill.shield-bash"]
    entity.skill_use_chance = 1.0
    entity.vigor = 100

    monkeypatch.setattr(entity_abilities.random, "random", lambda: 0.0)
    monkeypatch.setattr(entity_abilities, "get_skill_by_id", lambda _skill_id: {
        "skill_id": "skill.shield-bash",
        "name": "Shield Bash",
        "skill_type": "damage",
        "cast_type": "target",
        "vigor_cost": 10,
        "damage_dice_count": 1,
        "damage_dice_sides": 1,
        "damage_modifier": 0,
    })

    parts: list[dict] = []
    used = entity_abilities._entity_try_use_skill(session, entity, parts)

    assert used is False
    assert entity.vigor == 100
    assert parts == []


def test_entity_sleeping_does_not_cast_spell(monkeypatch) -> None:
    session = _make_session("client-player", "Lucia")
    entity = _make_entity("entity-priest", "Priest")
    entity.is_sleeping = True
    entity.spell_ids = ["spell.arcane-bolt"]
    entity.spell_use_chance = 1.0
    entity.mana = 100

    monkeypatch.setattr(entity_abilities.random, "random", lambda: 0.0)
    monkeypatch.setattr(entity_abilities, "get_spell_by_id", lambda _spell_id: {
        "spell_id": "spell.arcane-bolt",
        "name": "Arcane Bolt",
        "spell_type": "damage",
        "cast_type": "target",
        "mana_cost": 10,
        "damage_dice_count": 1,
        "damage_dice_sides": 1,
        "damage_modifier": 0,
    })

    parts: list[dict] = []
    casted = entity_abilities._entity_try_cast_spell(session, entity, parts)

    assert casted is False
    assert entity.mana == 100
    assert parts == []


def test_entity_spell_announcement_starts_on_new_line(monkeypatch) -> None:
    session = _make_session("client-player", "Lucia")
    entity = _make_entity("entity-hexer", "Crowbanner Hexer")
    entity.spell_ids = ["spell.coalburst"]
    entity.spell_use_chance = 1.0
    entity.mana = 100

    monkeypatch.setattr(entity_abilities.random, "random", lambda: 0.0)
    monkeypatch.setattr(entity_abilities.random, "choice", lambda options: options[0])
    monkeypatch.setattr(entity_abilities, "roll_spell_damage", lambda _spell, _bonus=0: 12)
    monkeypatch.setattr(entity_abilities, "get_spell_by_id", lambda _spell_id: {
        "spell_id": "spell.coalburst",
        "name": "Coalburst",
        "spell_type": "damage",
        "cast_type": "aoe",
        "mana_cost": 10,
        "damage_dice_count": 1,
        "damage_dice_sides": 1,
        "damage_modifier": 0,
    })

    parts: list[dict] = [{"text": "You annihilate a Crowbanner Hexer with your hit.", "fg": "bright_white", "bold": False}]
    casted = entity_abilities._entity_try_cast_spell(session, entity, parts)

    rendered = "".join(str(part.get("text", "")) for part in parts)
    assert casted is True
    assert "You annihilate a Crowbanner Hexer with your hit.\nA Crowbanner Hexer casts Coalburst across the room!" in rendered
