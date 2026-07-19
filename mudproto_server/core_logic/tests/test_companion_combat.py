import random

import combat
from combat import _apply_entity_attacks, begin_attack
from combat_state import start_combat
from companion_combat import resolve_companion_round
from models import ClientSession, EntityState
from protocol import utc_now_iso
from session_bootstrap import apply_player_class
from session_registry import shared_world_entities


def _make_session(client_id: str, name: str) -> ClientSession:
    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    session.entities = shared_world_entities
    return session


def _make_companion(owner_key: str, *, room_id: str = "start") -> EntityState:
    companion = EntityState(
        entity_id="companion-test",
        name="Bramble Squire",
        room_id=room_id,
        hit_points=140,
        max_hit_points=140,
    )
    companion.npc_id = "npc.companion-squire"
    companion.is_named = True
    companion.is_companion = True
    companion.is_ally = True
    companion.owner_player_key = owner_key
    companion.power_level = 3
    companion.attacks_per_round = 1
    companion.spawn_sequence = 50
    return companion


def _make_enemy(*, room_id: str = "start") -> EntityState:
    enemy = EntityState(
        entity_id="enemy-test",
        name="Hall Scout",
        room_id=room_id,
        hit_points=200,
        max_hit_points=200,
    )
    enemy.armor_class = 0
    enemy.power_level = 10
    enemy.spawn_sequence = 1
    return enemy


def test_companion_melee_damages_target_and_credits_owner() -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        random.seed(4242)
        owner = _make_session("melee-owner", "Meleeowner")
        owner.is_authenticated = False  # keep the heal scan out of this test
        companion = _make_companion("melee-owner")
        companion.owner_player_key = "meleeowner"
        enemy = _make_enemy()
        shared_world_entities[companion.entity_id] = companion
        shared_world_entities[enemy.entity_id] = enemy

        parts: list[dict] = []
        for _ in range(10):
            resolve_companion_round(owner, companion, enemy, parts)

        assert enemy.hit_points < 200
        assert "meleeowner" in enemy.experience_contributor_keys
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "Bramble Squire" in rendered
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_companion_heals_hurt_owner_with_target_heal_spell() -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("heal-owner", "Healowner")
        apply_player_class(owner, "class.monk", roll_attributes=True, initialize_progression=True)
        owner.status.hit_points = 1

        medic = _make_companion("healowner")
        medic.name = "Field Medic Ora"
        medic.npc_id = "npc.companion-field-medic"
        medic.mana = 80
        medic.max_mana = 80
        medic.spell_ids = ["spell.mending-word"]
        shared_world_entities[medic.entity_id] = medic

        parts: list[dict] = []
        resolve_companion_round(owner, medic, None, parts)

        assert owner.status.hit_points > 1
        assert medic.mana == 62
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "Mending Word" in rendered
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_companion_does_not_heal_healthy_owner() -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("healthy-owner", "Healthyowner")
        apply_player_class(owner, "class.monk", roll_attributes=True, initialize_progression=True)

        medic = _make_companion("healthyowner")
        medic.npc_id = "npc.companion-field-medic"
        medic.mana = 80
        medic.max_mana = 80
        medic.spell_ids = ["spell.mending-word"]
        shared_world_entities[medic.entity_id] = medic

        parts: list[dict] = []
        resolve_companion_round(owner, medic, None, parts)

        assert medic.mana == 80
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_enemy_melee_stays_on_player_unless_hard_engaged(monkeypatch) -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("no-intercept-owner", "Nointerceptowner")
        companion = _make_companion("nointerceptowner")
        companion.armor_class = 0
        enemy = _make_enemy()
        shared_world_entities[companion.entity_id] = companion
        shared_world_entities[enemy.entity_id] = enemy

        monkeypatch.setattr(combat.random, "random", lambda: 0.0)

        parts: list[dict] = []
        _apply_entity_attacks(owner, enemy, parts, allow_off_hand=False)

        # The companion is present but not hard-engaged, so it is never hit.
        assert companion.hit_points == 140
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "Bramble Squire" not in rendered
        assert "turns and" not in rendered
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_companion_death_removes_entity_and_roster_entry(monkeypatch) -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("slain-owner", "Slainowner")
        owner.companion_roster = [{"npc_id": "npc.companion-squire", "name": "Bramble Squire"}]
        companion = _make_companion("slainowner")
        companion.hit_points = 1
        companion.armor_class = 0
        enemy = _make_enemy()
        enemy.hard_target_companion_id = companion.entity_id
        shared_world_entities[companion.entity_id] = companion
        shared_world_entities[enemy.entity_id] = enemy

        monkeypatch.setattr(combat.random, "random", lambda: 0.99)

        parts: list[dict] = []
        _apply_entity_attacks(owner, enemy, parts, allow_off_hand=False)

        assert companion.entity_id not in shared_world_entities
        assert owner.companion_roster == []
        assert any(corpse.source_entity_id == companion.entity_id for corpse in owner.corpses.values())
        assert enemy.hard_target_companion_id == ""
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "has been slain!" in rendered
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_owner_cannot_attack_enlisted_companion() -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("guard-owner", "Guardowner")
        companion = _make_companion("guardowner")
        shared_world_entities[companion.entity_id] = companion

        outbound = begin_attack(owner, "bramble")

        assert outbound["payload"]["is_error"] is True
        assert companion.entity_id not in owner.combat.engaged_entity_ids

        assert start_combat(owner, companion.entity_id, "player") is False
        assert companion.entity_id not in owner.combat.engaged_entity_ids
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_companion_lines_stay_in_player_phase_when_room_round_is_split() -> None:
    from companion_combat import _companion_part
    from display_core import build_part
    from server_broadcasts import _split_actor_round_lines

    lines = [
        [build_part("You slash a hall scout.")],
        [_companion_part("Bramble Squire jabs a hall scout.")],
        [build_part("A hall scout is dead!")],
        [build_part("A hall scout claws you.")],
    ]

    player_lines, retaliation_lines = _split_actor_round_lines(lines, "you ")

    assert len(player_lines) == 3
    assert len(retaliation_lines) == 1
    assert "claws you" in "".join(str(part.get("text", "")) for part in retaliation_lines[0])


def test_companion_heals_hurt_companion_ally() -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("squad-owner", "Squadowner")
        apply_player_class(owner, "class.monk", roll_attributes=True, initialize_progression=True)

        hurt_squire = _make_companion("squadowner")
        hurt_squire.hit_points = 10
        shared_world_entities[hurt_squire.entity_id] = hurt_squire

        medic = _make_companion("squadowner")
        medic.entity_id = "companion-medic"
        medic.name = "Field Medic Ora"
        medic.npc_id = "npc.companion-field-medic"
        medic.mana = 80
        medic.max_mana = 80
        medic.spell_ids = ["spell.mending-word"]
        shared_world_entities[medic.entity_id] = medic

        parts: list[dict] = []
        resolve_companion_round(owner, medic, None, parts)

        assert hurt_squire.hit_points > 10
        assert medic.mana == 62
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "Bramble Squire" in rendered
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


RESCUE_SKILL = {
    "skill_id": "skill.rescue",
    "name": "Rescue",
    "description": "You hurl yourself into danger and drag a companion clear of the worst of the assault.",
    "skill_type": "support",
    "element": "physical",
    "cast_type": "target",
    "vigor_cost": 8,
    "usable_out_of_combat": False,
    "scaling_attribute_id": "",
    "scaling_multiplier": 0.0,
    "level_scaling_multiplier": 0.0,
    "support_effect": "",
    "support_amount": 0,
    "support_mode": "instant",
    "support_context": "You throw yourself into the fray and draw an enemy's fury away.",
    "observer_action": "[actor_name] lunges into the fray to rescue an ally.",
    "observer_context": "[actor_name] throws [actor_possessive] body between an ally and danger.",
    "lag_rounds": 3,
    "cooldown_rounds": 2,
}


def test_rescue_releases_pinned_companion(monkeypatch) -> None:
    import combat_player_abilities

    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("rescue-owner", "Rescueowner")
        owner.status.vigor = 50
        companion = _make_companion("rescueowner")
        enemy = _make_enemy()
        enemy.hard_target_companion_id = companion.entity_id
        shared_world_entities[companion.entity_id] = companion
        shared_world_entities[enemy.entity_id] = enemy
        owner.combat.engaged_entity_ids.add(enemy.entity_id)

        outbound, applied = combat_player_abilities.use_skill(owner, RESCUE_SKILL, "bramble")

        assert applied is True
        assert companion.rescue_guard_rounds_remaining == 3
        assert enemy.hard_target_companion_id == ""
        assert owner.status.vigor == 42
        rendered = "".join(
            str(part.get("text", ""))
            for message in (outbound if isinstance(outbound, list) else [outbound])
            for line in message.get("payload", {}).get("lines", [])
            if isinstance(line, list)
            for part in line
            if isinstance(part, dict)
        )
        assert "You shield Bramble Squire" in rendered

        # With the engagement released, enemy melee returns to the owner.
        monkeypatch.setattr(combat.random, "random", lambda: 0.0)
        parts: list[dict] = []
        _apply_entity_attacks(owner, enemy, parts, allow_off_hand=False)
        assert companion.hit_points == 140
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_rescue_fails_when_ally_is_engaged_but_not_targeted() -> None:
    import combat_player_abilities

    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("untargeted-rescue-owner", "Untargetedrescuer")
        owner.status.vigor = 50
        companion = _make_companion("untargetedrescuer")
        enemy = _make_enemy()
        enemy.combat_target_player_key = "untargetedrescuer"
        shared_world_entities[companion.entity_id] = companion
        shared_world_entities[enemy.entity_id] = enemy
        owner.combat.engaged_entity_ids.add(enemy.entity_id)

        outbound, applied = combat_player_abilities.use_skill(owner, RESCUE_SKILL, "bramble")

        assert applied is False
        assert owner.status.vigor == 50
        assert companion.rescue_guard_rounds_remaining == 0
        assert outbound["payload"]["is_error"] is True
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_rescue_companion_fails_without_a_threat_and_refunds_vigor() -> None:
    import combat_player_abilities

    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("safe-rescue-owner", "Saferescuer")
        owner.status.vigor = 50
        companion = _make_companion("saferescueowner")
        companion.owner_player_key = "saferescuer"
        shared_world_entities[companion.entity_id] = companion

        outbound, applied = combat_player_abilities.use_skill(owner, RESCUE_SKILL, "bramble")

        assert applied is False
        assert owner.status.vigor == 50
        assert companion.rescue_guard_rounds_remaining == 0
        assert outbound["payload"]["is_error"] is True
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_prompt_shows_companion_tank_like_a_player_tank() -> None:
    from display_feedback import build_prompt_parts
    from session_registry import connected_clients

    previous_entities = dict(shared_world_entities)
    previous_connected = dict(connected_clients)
    try:
        shared_world_entities.clear()
        connected_clients.clear()

        owner = _make_session("tank-prompt-owner", "Tankwatcher")
        apply_player_class(owner, "class.monk", roll_attributes=True, initialize_progression=True)
        companion = _make_companion("tank-prompt-owner")
        companion.owner_player_key = "tankwatcher"
        enemy = _make_enemy()
        shared_world_entities[companion.entity_id] = companion
        shared_world_entities[enemy.entity_id] = enemy
        owner.combat.engaged_entity_ids.add(enemy.entity_id)

        def _render_prompt() -> str:
            return "".join(str(part.get("text", "")) for part in build_prompt_parts(owner))

        # Enemy attention on the prompt's own player: no tank bracket.
        enemy.combat_target_player_key = "tankwatcher"
        assert "[Bramble Squire:" not in _render_prompt()

        # A hard-engaged (taunted) companion earns the tank bracket.
        enemy.hard_target_companion_id = companion.entity_id
        companion_prompt = _render_prompt()
        assert "[Bramble Squire:Perfect]" in companion_prompt

        # Another player tanking renders in the identical format.
        enemy.hard_target_companion_id = ""
        tank = _make_session("tank-prompt-tank", "Shieldbearer")
        apply_player_class(tank, "class.monk", roll_attributes=True, initialize_progression=True)
        connected_clients[tank.client_id] = tank
        enemy.combat_target_player_key = "shieldbearer"
        player_prompt = _render_prompt()
        assert "[Shieldbearer:Perfect]" in player_prompt
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)
        connected_clients.clear()
        connected_clients.update(previous_connected)


def test_companion_heals_itself_when_hurt() -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("self-heal-owner", "Selfhealer")
        apply_player_class(owner, "class.monk", roll_attributes=True, initialize_progression=True)

        medic = _make_companion("selfhealer")
        medic.name = "Field Medic Ora"
        medic.npc_id = "npc.companion-field-medic"
        medic.hit_points = 10
        medic.mana = 80
        medic.max_mana = 80
        medic.spell_ids = ["spell.mending-word"]
        shared_world_entities[medic.entity_id] = medic

        parts: list[dict] = []
        resolve_companion_round(owner, medic, None, parts)

        assert medic.hit_points > 10
        assert medic.mana == 62
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "on themselves" in rendered
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_companion_heals_group_members_hurt_companion() -> None:
    from session_registry import connected_clients

    previous_entities = dict(shared_world_entities)
    previous_connected = dict(connected_clients)
    try:
        shared_world_entities.clear()
        connected_clients.clear()

        owner = _make_session("squad-heal-owner", "Squadhealer")
        apply_player_class(owner, "class.monk", roll_attributes=True, initialize_progression=True)
        member = _make_session("squad-heal-member", "Squadmate")
        apply_player_class(member, "class.monk", roll_attributes=True, initialize_progression=True)
        connected_clients[owner.client_id] = owner
        connected_clients[member.client_id] = member
        member.following_player_key = "squadhealer"
        member.group_leader_key = "squadhealer"
        owner.group_member_keys.add("squadmate")

        member_squire = _make_companion("squadmate")
        member_squire.entity_id = "companion-member-squire"
        member_squire.hit_points = 10
        shared_world_entities[member_squire.entity_id] = member_squire

        medic = _make_companion("squadhealer")
        medic.entity_id = "companion-owner-medic"
        medic.name = "Field Medic Ora"
        medic.npc_id = "npc.companion-field-medic"
        medic.mana = 80
        medic.max_mana = 80
        medic.spell_ids = ["spell.mending-word"]
        shared_world_entities[medic.entity_id] = medic

        parts: list[dict] = []
        resolve_companion_round(owner, medic, None, parts)

        assert member_squire.hit_points > 10
        assert medic.mana == 62
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "Bramble Squire" in rendered
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)
        connected_clients.clear()
        connected_clients.update(previous_connected)


def _make_guardian(owner_key: str) -> EntityState:
    guardian = _make_companion(owner_key)
    guardian.entity_id = "companion-guardian"
    guardian.name = "Genenado The Brute"
    guardian.npc_id = "npc.companion-brute"
    guardian.is_guardian = True
    guardian.hit_points = 320
    guardian.max_hit_points = 320
    guardian.pronoun_possessive = "his"
    return guardian


def test_guardian_taunts_enemies_targeting_allies(monkeypatch) -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("taunt-owner", "Tauntowner")
        apply_player_class(owner, "class.monk", roll_attributes=True, initialize_progression=True)
        guardian = _make_guardian("taunt-owner")
        guardian.owner_player_key = "tauntowner"
        enemy = _make_enemy()
        enemy.combat_target_player_key = "tauntowner"
        shared_world_entities[guardian.entity_id] = guardian
        shared_world_entities[enemy.entity_id] = enemy
        owner.combat.engaged_entity_ids.add(enemy.entity_id)

        monkeypatch.setattr(random, "random", lambda: 0.0)

        parts: list[dict] = []
        resolve_companion_round(owner, guardian, enemy, parts)

        assert enemy.hard_target_companion_id == guardian.entity_id
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "bellows a challenge" in rendered
        assert "turns its fury on" in rendered
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_guardian_taunt_rolls_each_enemy_separately(monkeypatch) -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("multi-taunt-owner", "Multitauntowner")
        owner.is_authenticated = False  # keep the heal scan out of this test
        guardian = _make_guardian("multi-taunt-owner")
        guardian.owner_player_key = "multitauntowner"

        first_enemy = _make_enemy()
        first_enemy.combat_target_player_key = "multitauntowner"
        second_enemy = _make_enemy()
        second_enemy.entity_id = "enemy-second"
        second_enemy.name = "Crow Reaver"
        second_enemy.combat_target_player_key = "multitauntowner"
        shared_world_entities[guardian.entity_id] = guardian
        shared_world_entities[first_enemy.entity_id] = first_enemy
        shared_world_entities[second_enemy.entity_id] = second_enemy
        owner.combat.engaged_entity_ids.add(first_enemy.entity_id)
        owner.combat.engaged_entity_ids.add(second_enemy.entity_id)

        taunt_rolls = [0.0, 0.99]
        monkeypatch.setattr(random, "random", lambda: taunt_rolls.pop(0) if taunt_rolls else 0.99)

        parts: list[dict] = []
        resolve_companion_round(owner, guardian, first_enemy, parts)

        assert first_enemy.hard_target_companion_id == guardian.entity_id
        assert second_enemy.hard_target_companion_id == ""
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "turns its fury on" in rendered
        assert "refuses to be baited" in rendered
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_guardian_fights_normally_when_no_ally_is_threatened(monkeypatch) -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("calm-taunt-owner", "Calmtauntowner")
        owner.is_authenticated = False  # keep the heal scan out of this test
        guardian = _make_guardian("calm-taunt-owner")
        guardian.owner_player_key = "calmtauntowner"
        enemy = _make_enemy()
        enemy.combat_target_player_key = ""
        enemy.hard_target_companion_id = guardian.entity_id
        shared_world_entities[guardian.entity_id] = guardian
        shared_world_entities[enemy.entity_id] = enemy

        monkeypatch.setattr(random, "random", lambda: 0.99)  # suppress skill usage

        parts: list[dict] = []
        resolve_companion_round(owner, guardian, enemy, parts)

        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "bellows a challenge" not in rendered
        assert enemy.hit_points < 200
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)



def test_hard_engaged_enemy_spends_its_whole_turn_on_the_guardian(monkeypatch) -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("hard-owner", "Hardowner")
        guardian = _make_guardian("hardowner")
        guardian.hit_points = 5000
        guardian.max_hit_points = 5000
        guardian.armor_class = 0
        enemy = _make_enemy()
        enemy.attacks_per_round = 2
        enemy.off_hand_attacks_per_round = 1
        enemy.hard_target_companion_id = guardian.entity_id
        shared_world_entities[guardian.entity_id] = guardian
        shared_world_entities[enemy.entity_id] = enemy

        owner_hit_points_before = owner.status.hit_points
        monkeypatch.setattr(combat.random, "random", lambda: 0.99)

        parts: list[dict] = []
        _apply_entity_attacks(owner, enemy, parts, allow_off_hand=True)

        assert owner.status.hit_points == owner_hit_points_before
        assert guardian.hit_points < 5000
        assert enemy.hard_target_companion_id == guardian.entity_id
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "turns and" not in rendered
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_rescue_releases_hard_engagement(monkeypatch) -> None:
    from companions import rescue_companion

    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("release-owner", "Releaseowner")
        guardian = _make_guardian("releaseowner")
        enemy = _make_enemy()
        enemy.hard_target_companion_id = guardian.entity_id
        shared_world_entities[guardian.entity_id] = guardian
        shared_world_entities[enemy.entity_id] = enemy
        owner.combat.engaged_entity_ids.add(enemy.entity_id)

        guarded, rescue_error = rescue_companion(owner, guardian)

        assert guarded is True
        assert rescue_error is None
        assert guardian.rescue_guard_rounds_remaining == 3
        assert enemy.hard_target_companion_id == ""
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_companion_victory_quip_lands_in_the_player_phase(monkeypatch) -> None:
    from combat import _append_companion_victory_quip

    companion = _make_companion("quip-owner")
    companion.voice_lines = {"victory": ["Test quip line."]}

    monkeypatch.setattr(combat.random, "random", lambda: 0.0)

    parts: list[dict] = []
    _append_companion_victory_quip([companion], parts)

    quip_parts = [part for part in parts if str(part.get("text", "")) == "Test quip line."]
    assert len(quip_parts) == 1
    assert quip_parts[0].get("player_phase") is True

    # Without matching voice lines nothing is emitted and no RNG is consumed.
    silent_companion = _make_companion("quiet-owner")
    silent_parts: list[dict] = []
    _append_companion_victory_quip([silent_companion], silent_parts)
    assert silent_parts == []


def _make_field_medic(owner_key: str) -> EntityState:
    medic = _make_companion(owner_key)
    medic.name = "Field Medic Ora"
    medic.npc_id = "npc.companion-field-medic"
    medic.pronoun_possessive = "her"
    medic.mana = 120
    medic.max_mana = 120
    medic.spell_ids = ["spell.mending-word", "spell.field-dressing", "spell.arc-bolt"]
    return medic


def test_medic_casts_nothing_when_everyone_is_healthy(monkeypatch) -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("healthy-ward-owner", "Healthywardowner")
        apply_player_class(owner, "class.monk", roll_attributes=True, initialize_progression=True)

        medic = _make_field_medic("healthywardowner")
        enemy = _make_enemy()
        shared_world_entities[medic.entity_id] = medic
        shared_world_entities[enemy.entity_id] = enemy

        monkeypatch.setattr(random, "random", lambda: 0.99)  # suppress offensive casts

        parts: list[dict] = []
        resolve_companion_round(owner, medic, enemy, parts)

        assert medic.mana == 120
        assert medic.active_affects == []
        assert owner.active_affects == []
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_medic_dresses_a_hurt_ally_then_switches_to_burst_heals(monkeypatch) -> None:
    from player_resources import get_player_resource_caps

    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("dressing-owner", "Dressingowner")
        apply_player_class(owner, "class.monk", roll_attributes=True, initialize_progression=True)
        caps = get_player_resource_caps(owner)
        owner.status.hit_points = int(caps["hit_points"] * 0.55)

        medic = _make_field_medic("dressingowner")
        enemy = _make_enemy()
        shared_world_entities[medic.entity_id] = medic
        shared_world_entities[enemy.entity_id] = enemy

        monkeypatch.setattr(random, "random", lambda: 0.99)  # suppress offensive casts

        parts: list[dict] = []
        resolve_companion_round(owner, medic, enemy, parts)

        # Moderately hurt: the ongoing ward goes on first.
        assert medic.mana == 96
        assert any(affect.affect_name == "Field Dressing" for affect in owner.active_affects)
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "casts Field Dressing on you" in rendered

        # Still hurt but already dressed: the next round uses the burst heal.
        hit_points_before = owner.status.hit_points
        resolve_companion_round(owner, medic, enemy, parts)
        assert medic.mana == 78
        assert owner.status.hit_points > hit_points_before
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "casts Mending Word on you" in rendered
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_medic_prefers_burst_heal_for_critically_hurt_allies(monkeypatch) -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("critical-owner", "Criticalowner")
        apply_player_class(owner, "class.monk", roll_attributes=True, initialize_progression=True)
        owner.status.hit_points = 1

        medic = _make_field_medic("criticalowner")
        enemy = _make_enemy()
        shared_world_entities[medic.entity_id] = medic
        shared_world_entities[enemy.entity_id] = enemy

        monkeypatch.setattr(random, "random", lambda: 0.99)  # suppress offensive casts

        parts: list[dict] = []
        resolve_companion_round(owner, medic, enemy, parts)

        assert medic.mana == 102
        assert owner.status.hit_points > 1
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "casts Mending Word on you" in rendered
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_medic_dresses_a_hurt_allied_companion(monkeypatch) -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("squad-dressing-owner", "Squaddressingowner")
        apply_player_class(owner, "class.monk", roll_attributes=True, initialize_progression=True)

        squire = _make_companion("squaddressingowner")
        squire.entity_id = "companion-hurt-squire"
        squire.hit_points = 80  # about 57 percent: hurt but not critical

        medic = _make_field_medic("squaddressingowner")
        medic.entity_id = "companion-squad-medic"
        enemy = _make_enemy()
        shared_world_entities[squire.entity_id] = squire
        shared_world_entities[medic.entity_id] = medic
        shared_world_entities[enemy.entity_id] = enemy

        monkeypatch.setattr(random, "random", lambda: 0.99)  # suppress offensive casts

        parts: list[dict] = []
        resolve_companion_round(owner, medic, enemy, parts)

        assert medic.mana == 96
        assert any(affect.affect_name == "Field Dressing" for affect in squire.active_affects)
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "casts Field Dressing on" in rendered
        assert "Bramble Squire" in rendered
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_fresh_aggro_does_not_prefer_guardians(monkeypatch) -> None:
    import asyncio

    import combat_state
    from combat_state import _pending_auto_aggro_due_monotonic, process_pending_auto_aggro
    from session_registry import active_character_sessions, connected_clients

    previous_entities = dict(shared_world_entities)
    previous_connected = dict(connected_clients)
    previous_active = dict(active_character_sessions)
    try:
        shared_world_entities.clear()
        connected_clients.clear()
        active_character_sessions.clear()

        owner = _make_session("aggro-uniform-owner", "Aggrouniformowner")
        connected_clients[owner.client_id] = owner

        guardian = _make_guardian("aggrouniformowner")
        enemy = _make_enemy()
        enemy.is_aggro = True
        shared_world_entities[guardian.entity_id] = guardian
        shared_world_entities[enemy.entity_id] = enemy

        # Uniform pool: the first slot is the player, guardian included after.
        monkeypatch.setattr(combat_state.random, "choice", lambda seq: seq[0])

        async def _run() -> None:
            _pending_auto_aggro_due_monotonic[enemy.entity_id] = 0.0
            process_pending_auto_aggro()

        asyncio.run(_run())

        assert enemy.entity_id in owner.combat.engaged_entity_ids
        assert enemy.hard_target_companion_id == ""
    finally:
        _pending_auto_aggro_due_monotonic.clear()
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)
        connected_clients.clear()
        connected_clients.update(previous_connected)
        active_character_sessions.clear()
        active_character_sessions.update(previous_active)



def test_fresh_aggro_can_pick_a_non_guardian_companion(monkeypatch) -> None:
    import asyncio

    import combat_state
    from combat_state import _pending_auto_aggro_due_monotonic, process_pending_auto_aggro
    from session_registry import active_character_sessions, connected_clients

    previous_entities = dict(shared_world_entities)
    previous_connected = dict(connected_clients)
    previous_active = dict(active_character_sessions)
    try:
        shared_world_entities.clear()
        connected_clients.clear()
        active_character_sessions.clear()

        owner = _make_session("aggro-medic-owner", "Aggromedicowner")
        connected_clients[owner.client_id] = owner

        medic = _make_companion("aggromedicowner")
        medic.entity_id = "companion-aggro-victim"
        enemy = _make_enemy()
        enemy.is_aggro = True
        shared_world_entities[medic.entity_id] = medic
        shared_world_entities[enemy.entity_id] = enemy

        monkeypatch.setattr(combat_state.random, "choice", lambda seq: seq[-1])

        async def _run() -> None:
            _pending_auto_aggro_due_monotonic[enemy.entity_id] = 0.0
            process_pending_auto_aggro()

        asyncio.run(_run())

        assert enemy.entity_id in owner.combat.engaged_entity_ids
        assert enemy.hard_target_companion_id == medic.entity_id
    finally:
        _pending_auto_aggro_due_monotonic.clear()
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)
        connected_clients.clear()
        connected_clients.update(previous_connected)
        active_character_sessions.clear()
        active_character_sessions.update(previous_active)


def test_fresh_aggro_can_still_pick_the_player(monkeypatch) -> None:
    import asyncio

    import combat_state
    from combat_state import _pending_auto_aggro_due_monotonic, process_pending_auto_aggro
    from session_registry import active_character_sessions, connected_clients

    previous_entities = dict(shared_world_entities)
    previous_connected = dict(connected_clients)
    previous_active = dict(active_character_sessions)
    try:
        shared_world_entities.clear()
        connected_clients.clear()
        active_character_sessions.clear()

        owner = _make_session("aggro-player-owner", "Aggroplayerowner")
        connected_clients[owner.client_id] = owner

        medic = _make_companion("aggroplayerowner")
        medic.entity_id = "companion-aggro-bystander"
        enemy = _make_enemy()
        enemy.is_aggro = True
        shared_world_entities[medic.entity_id] = medic
        shared_world_entities[enemy.entity_id] = enemy

        monkeypatch.setattr(combat_state.random, "choice", lambda seq: seq[0])

        async def _run() -> None:
            _pending_auto_aggro_due_monotonic[enemy.entity_id] = 0.0
            process_pending_auto_aggro()

        asyncio.run(_run())

        assert enemy.entity_id in owner.combat.engaged_entity_ids
        assert enemy.hard_target_companion_id == ""
    finally:
        _pending_auto_aggro_due_monotonic.clear()
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)
        connected_clients.clear()
        connected_clients.update(previous_connected)
        active_character_sessions.clear()
        active_character_sessions.update(previous_active)


def test_rescue_guarded_companion_is_not_aggro_bait() -> None:
    import asyncio

    from combat_state import _pending_auto_aggro_due_monotonic, process_pending_auto_aggro
    from session_registry import active_character_sessions, connected_clients

    previous_entities = dict(shared_world_entities)
    previous_connected = dict(connected_clients)
    previous_active = dict(active_character_sessions)
    try:
        shared_world_entities.clear()
        connected_clients.clear()
        active_character_sessions.clear()

        owner = _make_session("aggro-guarded-owner", "Aggroguardedowner")
        connected_clients[owner.client_id] = owner

        guardian = _make_guardian("aggroguardedowner")
        guardian.rescue_guard_rounds_remaining = 3
        enemy = _make_enemy()
        enemy.is_aggro = True
        shared_world_entities[guardian.entity_id] = guardian
        shared_world_entities[enemy.entity_id] = enemy

        async def _run() -> None:
            _pending_auto_aggro_due_monotonic[enemy.entity_id] = 0.0
            process_pending_auto_aggro()

        asyncio.run(_run())

        assert enemy.entity_id in owner.combat.engaged_entity_ids
        assert enemy.hard_target_companion_id == ""
    finally:
        _pending_auto_aggro_due_monotonic.clear()
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)
        connected_clients.clear()
        connected_clients.update(previous_connected)
        active_character_sessions.clear()
        active_character_sessions.update(previous_active)


def test_enemy_aoe_spell_hits_companions_in_the_room(monkeypatch) -> None:
    from combat_entity_abilities import _entity_try_cast_spell

    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("aoe-owner", "Aoeowner")
        owner.status.hit_points = 500
        companion = _make_companion("aoeowner")
        enemy = _make_enemy()
        enemy.mana = 100
        enemy.max_mana = 100
        enemy.spell_use_chance = 1.0
        enemy.spell_ids = ["spell.ember-lance"]
        shared_world_entities[companion.entity_id] = companion
        shared_world_entities[enemy.entity_id] = enemy

        monkeypatch.setattr(random, "random", lambda: 0.0)

        parts: list[dict] = []
        casted = _entity_try_cast_spell(owner, enemy, parts, aoe_secondary_lines={})

        assert casted is True
        assert owner.status.hit_points < 500
        assert companion.hit_points < 140
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "Bramble Squire" in rendered
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_enemy_aoe_can_slay_a_companion(monkeypatch) -> None:
    from combat_entity_abilities import _entity_try_cast_spell

    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("aoe-slain-owner", "Aoeslainowner")
        owner.status.hit_points = 500
        owner.companion_roster = [{"npc_id": "npc.companion-squire", "name": "Bramble Squire"}]
        companion = _make_companion("aoeslainowner")
        companion.hit_points = 1
        enemy = _make_enemy()
        enemy.mana = 100
        enemy.max_mana = 100
        enemy.spell_use_chance = 1.0
        enemy.spell_ids = ["spell.ember-lance"]
        shared_world_entities[companion.entity_id] = companion
        shared_world_entities[enemy.entity_id] = enemy

        monkeypatch.setattr(random, "random", lambda: 0.0)

        parts: list[dict] = []
        _entity_try_cast_spell(owner, enemy, parts, aoe_secondary_lines={})

        assert companion.entity_id not in shared_world_entities
        assert owner.companion_roster == []
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "has been slain!" in rendered
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_taunt_pulls_place_the_guardians_owner_in_battle(monkeypatch) -> None:
    from session_registry import connected_clients

    previous_entities = dict(shared_world_entities)
    previous_connected = dict(connected_clients)
    try:
        shared_world_entities.clear()
        connected_clients.clear()

        owner = _make_session("pulled-in-owner", "Pulledinowner")
        apply_player_class(owner, "class.monk", roll_attributes=True, initialize_progression=True)
        member = _make_session("pulled-in-member", "Pulledmate")
        apply_player_class(member, "class.monk", roll_attributes=True, initialize_progression=True)
        connected_clients[owner.client_id] = owner
        connected_clients[member.client_id] = member
        member.following_player_key = "pulledinowner"
        member.group_leader_key = "pulledinowner"
        owner.group_member_keys.add("pulledmate")

        guardian = _make_guardian("pulled-in-owner")
        guardian.owner_player_key = "pulledinowner"

        # The enemy is fighting a groupmate; the guardian's owner is idle.
        enemy = _make_enemy()
        enemy.combat_target_player_key = "pulledmate"
        shared_world_entities[guardian.entity_id] = guardian
        shared_world_entities[enemy.entity_id] = enemy
        assert enemy.entity_id not in owner.combat.engaged_entity_ids

        monkeypatch.setattr(random, "random", lambda: 0.0)

        parts: list[dict] = []
        resolve_companion_round(owner, guardian, None, parts)

        assert enemy.hard_target_companion_id == guardian.entity_id
        assert enemy.entity_id in owner.combat.engaged_entity_ids
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)
        connected_clients.clear()
        connected_clients.update(previous_connected)



def test_guardian_stands_down_when_another_guardian_holds_the_enemy(monkeypatch) -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("second-guardian-owner", "Secondguardianowner")
        owner.is_authenticated = False  # keep the heal scan out of this test
        own_guardian = _make_guardian("second-guardian-owner")
        own_guardian.owner_player_key = "secondguardianowner"

        other_guardian = _make_guardian("someone-else")
        other_guardian.entity_id = "companion-other-guardian"
        other_guardian.name = "Other Bulwark"

        enemy = _make_enemy()
        enemy.combat_target_player_key = "someone-else"
        enemy.hard_target_companion_id = other_guardian.entity_id
        shared_world_entities[own_guardian.entity_id] = own_guardian
        shared_world_entities[other_guardian.entity_id] = other_guardian
        shared_world_entities[enemy.entity_id] = enemy
        owner.combat.engaged_entity_ids.add(enemy.entity_id)

        monkeypatch.setattr(random, "random", lambda: 0.99)  # suppress skill usage

        parts: list[dict] = []
        resolve_companion_round(owner, own_guardian, enemy, parts)

        # The enemy is already held by a guardian: no taunt tug-of-war, and
        # the second guardian fights normally instead.
        assert enemy.hard_target_companion_id == other_guardian.entity_id
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "bellows a challenge" not in rendered
        assert enemy.hit_points < 200

        # An enemy held by a non-guardian companion is still worth taunting.
        medic = _make_companion("secondguardianowner")
        medic.entity_id = "companion-held-medic"
        shared_world_entities[medic.entity_id] = medic
        enemy.hard_target_companion_id = medic.entity_id
        monkeypatch.setattr(random, "random", lambda: 0.0)

        parts = []
        resolve_companion_round(owner, own_guardian, enemy, parts)

        assert enemy.hard_target_companion_id == own_guardian.entity_id
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "bellows a challenge" in rendered
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_guardian_ignores_fights_of_ungrouped_strangers(monkeypatch) -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("neutral-guardian-owner", "Neutralguardianowner")
        owner.is_authenticated = False  # keep the heal scan out of this test
        guardian = _make_guardian("neutral-guardian-owner")
        guardian.owner_player_key = "neutralguardianowner"

        enemy = _make_enemy()
        enemy.combat_target_player_key = "some-stranger"
        shared_world_entities[guardian.entity_id] = guardian
        shared_world_entities[enemy.entity_id] = enemy
        owner.combat.engaged_entity_ids.add(enemy.entity_id)

        monkeypatch.setattr(random, "random", lambda: 0.99)  # suppress skill usage

        parts: list[dict] = []
        resolve_companion_round(owner, guardian, enemy, parts)

        # A stranger's fight is not the guardian's problem: no taunt, and it
        # fights its owner's target normally instead.
        assert enemy.hard_target_companion_id == ""
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "bellows a challenge" not in rendered
        assert enemy.hit_points < 200
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)
