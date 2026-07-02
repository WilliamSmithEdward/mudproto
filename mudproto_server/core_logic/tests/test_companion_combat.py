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
        assert medic.mana == 68
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


def test_enemy_swings_intercepted_by_companion(monkeypatch) -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("intercept-owner", "Interceptowner")
        companion = _make_companion("interceptowner")
        companion.armor_class = 0
        enemy = _make_enemy()
        shared_world_entities[companion.entity_id] = companion
        shared_world_entities[enemy.entity_id] = enemy

        owner_hit_points_before = owner.status.hit_points
        monkeypatch.setattr(combat.random, "random", lambda: 0.0)

        parts: list[dict] = []
        _apply_entity_attacks(owner, enemy, parts, allow_off_hand=False)

        assert companion.hit_points < 140
        assert owner.status.hit_points == owner_hit_points_before
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "Bramble Squire" in rendered
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
        shared_world_entities[companion.entity_id] = companion
        shared_world_entities[enemy.entity_id] = enemy

        monkeypatch.setattr(combat.random, "random", lambda: 0.0)

        parts: list[dict] = []
        _apply_entity_attacks(owner, enemy, parts, allow_off_hand=False)

        assert companion.entity_id not in shared_world_entities
        assert owner.companion_roster == []
        assert any(corpse.source_entity_id == companion.entity_id for corpse in owner.corpses.values())
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
        assert medic.mana == 68
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


def test_rescue_guards_companion_from_interception(monkeypatch) -> None:
    import combat_player_abilities

    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("rescue-owner", "Rescueowner")
        owner.status.vigor = 50
        companion = _make_companion("rescueowner")
        enemy = _make_enemy()
        shared_world_entities[companion.entity_id] = companion
        shared_world_entities[enemy.entity_id] = enemy
        owner.combat.engaged_entity_ids.add(enemy.entity_id)

        outbound, applied = combat_player_abilities.use_skill(owner, RESCUE_SKILL, "bramble")

        assert applied is True
        assert companion.rescue_guard_rounds_remaining == 3
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

        # While the guard holds, forced-intercept swings stay on the owner.
        monkeypatch.setattr(combat.random, "random", lambda: 0.0)
        parts: list[dict] = []
        _apply_entity_attacks(owner, enemy, parts, allow_off_hand=False)
        assert companion.hit_points == 140
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

        # Companion tanking via interception.
        enemy.intercepting_companion_id = companion.entity_id
        companion_prompt = _render_prompt()
        assert "[Bramble Squire:Perfect]" in companion_prompt

        # Another player tanking renders in the identical format.
        enemy.intercepting_companion_id = ""
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


def test_interception_is_sticky_for_the_whole_enemy_turn(monkeypatch) -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        owner = _make_session("sticky-owner", "Stickyowner")
        companion = _make_companion("stickyowner")
        companion.hit_points = 1000
        companion.max_hit_points = 1000
        companion.armor_class = 0
        enemy = _make_enemy()
        enemy.attacks_per_round = 3
        shared_world_entities[companion.entity_id] = companion
        shared_world_entities[enemy.entity_id] = enemy

        owner_hit_points_before = owner.status.hit_points
        monkeypatch.setattr(combat.random, "random", lambda: 0.0)

        parts: list[dict] = []
        _apply_entity_attacks(owner, enemy, parts, allow_off_hand=False)

        assert owner.status.hit_points == owner_hit_points_before
        assert enemy.intercepting_companion_id == companion.entity_id

        monkeypatch.setattr(combat.random, "random", lambda: 0.99)
        parts = []
        _apply_entity_attacks(owner, enemy, parts, allow_off_hand=False)
        assert enemy.intercepting_companion_id == ""
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


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
        assert medic.mana == 68
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
        assert medic.mana == 68
        rendered = "".join(str(part.get("text", "")) for part in parts)
        assert "Bramble Squire" in rendered
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)
        connected_clients.clear()
        connected_clients.update(previous_connected)
