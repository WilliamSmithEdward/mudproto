"""Characterization test for _apply_player_attacks.

Pins the exact behavior of the player attack loops (main attack plus affect-based
extra main/off/unarmed hits) so the loops can be refactored without changing
output. The key subtlety: for a named target the main and unarmed loops omit the
indefinite article ("Gronk") while the main/off extra loops add it ("a Gronk").
A fixed RNG seed pins the damage rolls and the order of random draws.
"""

import random

import combat
from models import ActiveAffectState, ClientSession, EntityState


def _make_attack_session() -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id="c1", websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = "Hero"
    session.player_state_key = "hero"
    session.player.current_room_id = "start"
    session.player.level = 5
    session.active_affects = [
        ActiveAffectState(
            affect_id="affect.extra-hits",
            affect_name="Flurry",
            affect_mode="instant",
            affect_type="",
            extra_main_hand_hits=2,
            extra_off_hand_hits=2,
            extra_unarmed_hits=2,
        )
    ]
    return session


def _make_named_target() -> EntityState:
    return EntityState(
        entity_id="e1",
        name="Gronk",
        room_id="start",
        hit_points=100000,
        max_hit_points=100000,
        armor_class=-50,
        is_named=True,
    )


def test_player_attacks_named_extra_hits_snapshot() -> None:
    random.seed(12345)
    session = _make_attack_session()
    entity = _make_named_target()
    parts: list[dict] = []
    room_lines: list[list[dict]] = []

    combat._apply_player_attacks(session, entity, parts, room_lines, True)

    texts = [part["text"] for part in parts]
    name_renders = [text for text in texts if text in ("Gronk", "a Gronk")]

    assert name_renders == ["Gronk", "a Gronk", "a Gronk", "a Gronk", "a Gronk", "Gronk", "Gronk"]
    assert entity.hit_points == 99907
    assert len(parts) == 48
