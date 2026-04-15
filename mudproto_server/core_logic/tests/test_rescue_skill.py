import combat_player_abilities
import command_handlers.skills as skills_handler
from combat_state import get_session_combatant_key
from models import ClientSession, EntityState


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


def _make_session(client_id: str, name: str) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    return session


def _make_entity(entity_id: str, name: str, spawn_sequence: int) -> EntityState:
    entity = EntityState(
        entity_id=entity_id,
        name=name,
        room_id="start",
        hit_points=100,
        max_hit_points=100,
    )
    entity.spawn_sequence = spawn_sequence
    return entity


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


def test_rescue_redirects_single_attacker_and_ends_target_combat(monkeypatch) -> None:
    rescuer = _make_session("client-rescuer", "Lucia")
    rescued = _make_session("client-rescued", "Orlandu")
    attacker = _make_entity("entity-raider", "Raider", 1)

    rescuer.entities[attacker.entity_id] = attacker
    rescued.entities[attacker.entity_id] = attacker
    rescued.combat.engaged_entity_ids.add(attacker.entity_id)
    attacker.combat_target_player_key = get_session_combatant_key(rescued)

    monkeypatch.setattr(
        combat_player_abilities,
        "_resolve_room_player_selector",
        lambda _session, _target_name, require_exact_name=True: (rescued, None),
    )

    outbound, applied = combat_player_abilities.use_skill(rescuer, RESCUE_SKILL, "Orlandu")
    rendered = _extract_display_text(outbound)

    assert applied is True
    assert "Rescue" in rendered
    assert attacker.combat_target_player_key == get_session_combatant_key(rescuer)
    assert attacker.entity_id in rescuer.combat.engaged_entity_ids
    assert rescued.combat.engaged_entity_ids == set()


def test_rescue_redirects_only_one_attacker(monkeypatch) -> None:
    rescuer = _make_session("client-rescuer-many", "Lucia")
    rescued = _make_session("client-rescued-many", "Orlandu")
    first_attacker = _make_entity("entity-first", "First Raider", 1)
    second_attacker = _make_entity("entity-second", "Second Raider", 2)

    for entity in (first_attacker, second_attacker):
        rescuer.entities[entity.entity_id] = entity
        rescued.entities[entity.entity_id] = entity
        rescued.combat.engaged_entity_ids.add(entity.entity_id)
        entity.combat_target_player_key = get_session_combatant_key(rescued)

    monkeypatch.setattr(
        combat_player_abilities,
        "_resolve_room_player_selector",
        lambda _session, _target_name, require_exact_name=True: (rescued, None),
    )

    _, applied = combat_player_abilities.use_skill(rescuer, RESCUE_SKILL, "Orlandu")

    assert applied is True
    assert first_attacker.combat_target_player_key == get_session_combatant_key(rescuer)
    assert second_attacker.combat_target_player_key == get_session_combatant_key(rescued)
    assert rescuer.combat.engaged_entity_ids == {first_attacker.entity_id}
    assert rescued.combat.engaged_entity_ids == {second_attacker.entity_id}


def test_rescue_errors_when_target_is_not_under_attack(monkeypatch) -> None:
    rescuer = _make_session("client-rescuer-safe", "Lucia")
    rescued = _make_session("client-rescued-safe", "Orlandu")

    monkeypatch.setattr(
        combat_player_abilities,
        "_resolve_room_player_selector",
        lambda _session, _target_name, require_exact_name=True: (rescued, None),
    )

    outbound, applied = combat_player_abilities.use_skill(rescuer, RESCUE_SKILL, "Orlandu")
    rendered = _extract_display_text(outbound)

    assert applied is False
    assert "needs no rescuing" in rendered.lower()


def test_rescue_applies_three_round_command_lag(monkeypatch) -> None:
    rescuer = _make_session("client-rescuer-lag", "Lucia")
    rescued = _make_session("client-rescued-lag", "Orlandu")
    attacker = _make_entity("entity-lag-raider", "Lag Raider", 1)
    rescuer.known_skill_ids = ["skill.rescue"]

    rescuer.entities[attacker.entity_id] = attacker
    rescued.entities[attacker.entity_id] = attacker
    rescued.combat.engaged_entity_ids.add(attacker.entity_id)
    attacker.combat_target_player_key = get_session_combatant_key(rescued)

    applied_lag: list[float] = []
    monkeypatch.setattr(
        combat_player_abilities,
        "_resolve_room_player_selector",
        lambda _session, _target_name, require_exact_name=True: (rescued, None),
    )
    monkeypatch.setattr(skills_handler, "apply_lag", lambda _session, seconds: applied_lag.append(seconds))

    response = skills_handler.handle_skill_fallback_command(rescuer, "rescue", ["Orlandu"], "rescue Orlandu")
    rendered = _extract_display_text(response)

    assert "Rescue" in rendered
    assert applied_lag == [3 * skills_handler.COMBAT_ROUND_INTERVAL_SECONDS]
