import combat
from models import ClientSession, EntityState


def _make_session(client_id: str, name: str) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    return session


def test_player_hit_text_uses_overkill_damage_severity(monkeypatch) -> None:
    session = _make_session("client-overkill", "Lucia")
    entity = EntityState(
        entity_id="entity-reaver",
        name="East Watch Reaver",
        room_id="start",
        hit_points=1,
        max_hit_points=100,
    )

    monkeypatch.setattr(combat, "_build_player_attack_sequence", lambda _session, _allow_off_hand: [None])
    monkeypatch.setattr(combat, "roll_hit", lambda _hit_mod, _armor_class: True)
    monkeypatch.setattr(combat, "get_player_hit_modifier", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(combat, "roll_player_damage", lambda *_args, **_kwargs: (50, "", "hit"))
    monkeypatch.setattr(combat, "_mark_entity_contributor", lambda _session, _entity: None)
    monkeypatch.setattr(combat, "_apply_weapon_room_damage_proc", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat, "_apply_weapon_target_damage_proc", lambda *_args, **_kwargs: None)

    parts: list[dict] = []
    combat._apply_player_attacks(session, entity, parts, room_broadcast_lines=[], allow_off_hand=False)

    rendered = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
    assert "annihilate" in rendered.lower()
    assert "barely" not in rendered.lower()
