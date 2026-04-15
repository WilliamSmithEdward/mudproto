import display_character
from models import ActiveAffectState, ActiveSupportEffectState, ClientSession


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
    session.active_support_effects.append(ActiveSupportEffectState(
        spell_id="spell.regeneration-ward",
        spell_name="Regeneration Ward",
        support_mode="timed",
        support_effect="heal",
        support_amount=12,
        remaining_hours=2,
    ))
    session.active_affects.append(ActiveAffectState(
        affect_id="affect.fist-flurry",
        affect_name="Fist Flurry",
        affect_mode="battle_rounds",
        affect_type="extra_unarmed_hits",
        remaining_rounds=3,
    ))

    outbound = display_character.display_score(session)
    rendered = _extract_display_text(outbound)

    assert "Regeneration Ward (2 hours remaining)" in rendered
    assert "Fist Flurry (3 rounds remaining)" in rendered
