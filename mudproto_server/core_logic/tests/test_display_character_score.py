import display_character
import combat_player_abilities
from models import ActiveAffectState, ClientSession


def _make_session(client_id: str, name: str) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    return session


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


def test_score_displays_standing_posture() -> None:
    session = _make_session("client-score-standing", "Lucia")

    outbound = display_character.display_score(session)
    rendered = _extract_display_text(outbound)

    assert "Posture: Standing" in rendered


def test_score_displays_sitting_posture() -> None:
    session = _make_session("client-score-sitting", "Lucia")
    session.is_sitting = True

    outbound = display_character.display_score(session)
    rendered = _extract_display_text(outbound)

    assert "Posture: Sitting" in rendered


def test_score_displays_resting_posture() -> None:
    session = _make_session("client-score-resting", "Lucia")
    session.is_resting = True

    outbound = display_character.display_score(session)
    rendered = _extract_display_text(outbound)

    assert "Posture: Resting" in rendered


def test_score_displays_sleeping_posture() -> None:
    session = _make_session("client-score-sleeping", "Lucia")
    session.is_sleeping = True

    outbound = display_character.display_score(session)
    rendered = _extract_display_text(outbound)

    assert "Posture: Sleeping" in rendered


def test_score_displays_active_affects_and_support_effects() -> None:
    session = _make_session("client-score-effects", "Lucia")
    session.active_affects.append(ActiveAffectState(
        affect_id="affect.regeneration",
        affect_name="Regeneration Ward",
        affect_mode="timed",
        affect_type="regeneration",
        target_resource="hit_points",
        affect_amount=12,
        remaining_hours=2,
    ))
    session.active_affects.append(ActiveAffectState(
        affect_id="affect.extra-hits",
        affect_name="Fist Flurry",
        affect_mode="battle_rounds",
        affect_type="extra_unarmed_hits",
        affect_descriptor="Extra Hits",
        remaining_rounds=3,
    ))

    outbound = display_character.display_score(session)
    rendered = _extract_display_text(outbound)

    assert "Regeneration Ward" in rendered
    assert "2 hours remaining" in rendered
    assert "Fist Flurry (Extra Hits, 3 rounds remaining)" in rendered


def test_score_displays_targeted_support_spell_affect_from_another_player(monkeypatch) -> None:
    caster = _make_session("client-caster", "Lucia")
    target = _make_session("client-target", "Orlandu")

    spell = {
        "spell_id": "spell.regeneration-ward",
        "name": "Regeneration Ward",
        "school": "Restoration",
        "spell_type": "support",
        "element": "restoration",
        "cast_type": "target",
        "mana_cost": 5,
        "support_effect": "heal",
        "support_amount": 1,
        "support_mode": "instant",
        "support_context": "A pale ward settles around you, knitting your wounds with each heartbeat of battle.",
        "affect_ids": [{
            "affect_id": "affect.regeneration",
            "name": "Regeneration Ward",
            "target": "target",
            "affect_mode": "battle_rounds",
            "target_resource": "hit_points",
            "amount": 0,
            "dice_count": 1,
            "dice_sides": 21,
            "roll_modifier": 39,
            "duration_rounds": 3,
        }],
    }

    monkeypatch.setattr(
        combat_player_abilities,
        "_resolve_room_player_selector",
        lambda _session, _target_name, require_exact_name=True: (target, None),
    )

    outbound, applied = combat_player_abilities.cast_spell(caster, spell, "Orlandu")
    rendered = _extract_display_text(outbound)
    score_rendered = _extract_display_text(display_character.display_score(target))

    assert applied is True
    assert "Regeneration Ward" in rendered
    assert "Regeneration Ward (Health Regeneration, 3 rounds remaining)" in score_rendered


def test_score_displays_damage_affect_labels() -> None:
    session = _make_session("client-score-damage-label", "Lucia")
    session.active_affects.append(ActiveAffectState(
        affect_id="affect.dealt-damage",
        affect_name="Battle Focus",
        affect_mode="battle_rounds",
        affect_type="damage_dealt_multiplier",
        affect_descriptor="Damage Dealt",
        can_be_negative=True,
        affect_amount=0.2,
        remaining_rounds=2,
    ))

    rendered = _extract_display_text(display_character.display_score(session))

    assert "Battle Focus (Increased Damage Dealt, 2 rounds remaining)" in rendered


def test_score_displays_specific_resource_regeneration_label() -> None:
    session = _make_session("client-score-mana-regen-label", "Lucia")
    session.active_affects.append(ActiveAffectState(
        affect_id="affect.regeneration",
        affect_name="Clarity Ward",
        affect_mode="battle_rounds",
        affect_type="regeneration",
        affect_descriptor="Regeneration",
        target_resource="mana",
        remaining_rounds=2,
    ))

    rendered = _extract_display_text(display_character.display_score(session))

    assert "Clarity Ward (Mana Regeneration, 2 rounds remaining)" in rendered


def test_score_uses_template_name_dynamically_for_affect_label() -> None:
    session = _make_session("client-score-dynamic-affect-label", "Lucia")
    session.active_affects.append(ActiveAffectState(
        affect_id="affect.custom-template-name",
        affect_name="Battle Focus",
        affect_mode="battle_rounds",
        affect_type="damage_dealt_multiplier",
        affect_descriptor="Mystic Pressure",
        can_be_negative=True,
        affect_amount=0.2,
        remaining_rounds=2,
    ))

    rendered = _extract_display_text(display_character.display_score(session))

    assert "Battle Focus (Increased Mystic Pressure, 2 rounds remaining)" in rendered


def test_score_displays_reduced_negative_affect_label() -> None:
    session = _make_session("client-score-reduced-affect-label", "Lucia")
    session.active_affects.append(ActiveAffectState(
        affect_id="affect.received-damage",
        affect_name="Centered Guard",
        affect_mode="battle_rounds",
        affect_type="damage_received_multiplier",
        affect_descriptor="Damage Received",
        can_be_negative=True,
        affect_amount=-0.12,
        remaining_rounds=2,
    ))

    rendered = _extract_display_text(display_character.display_score(session))

    assert "Centered Guard (Reduced Damage Received, 2 rounds remaining)" in rendered


def test_score_displays_targeted_ongoing_support_spell_from_another_player(monkeypatch) -> None:
    caster = _make_session("client-caster-ongoing", "Lucia")
    target = _make_session("client-target-ongoing", "Orlandu")

    spell = {
        "spell_id": "spell.guardian-light",
        "name": "Guardian Light",
        "school": "Restoration",
        "spell_type": "support",
        "element": "restoration",
        "cast_type": "target",
        "mana_cost": 5,
        "support_effect": "heal",
        "support_amount": 0,
        "support_dice_count": 0,
        "support_mode": "instant",
        "duration_rounds": 2,
        "support_context": "A steady ward shines over you.",
        "affect_ids": [
            {
                "affect_id": "affect.regeneration",
                "name": "Guardian Light",
                "affect_mode": "battle_rounds",
                "duration_rounds": 2,
                "target": "target",
                "target_resource": "hit_points",
                "affect_amount": 6,
            }
        ],
    }

    monkeypatch.setattr(
        combat_player_abilities,
        "_resolve_room_player_selector",
        lambda _session, _target_name, require_exact_name=True: (target, None),
    )

    _, applied = combat_player_abilities.cast_spell(caster, spell, "Orlandu")
    score_rendered = _extract_display_text(display_character.display_score(target))

    assert applied is True
    assert "Guardian Light" in score_rendered
    assert "2 rounds remaining" in score_rendered
