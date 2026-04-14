import display_room
from models import ClientSession, EntityState
from world import Room


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


def test_display_room_shows_npc_posture_labels(monkeypatch) -> None:
    viewer = _make_session("client-viewer", "Lucia")
    room = Room(room_id="start", title="Start", description="A room.")

    standing_entity = EntityState(
        entity_id="entity-standing",
        name="Sentry",
        room_id="start",
        hit_points=100,
        max_hit_points=100,
    )
    sitting_entity = EntityState(
        entity_id="entity-sitting",
        name="Bandit",
        room_id="start",
        hit_points=100,
        max_hit_points=100,
        is_sitting=True,
    )
    resting_entity = EntityState(
        entity_id="entity-resting",
        name="Priest",
        room_id="start",
        hit_points=100,
        max_hit_points=100,
        is_resting=True,
    )

    monkeypatch.setattr(display_room, "list_room_entities", lambda _session, _room_id: [standing_entity, sitting_entity, resting_entity])
    monkeypatch.setattr(display_room, "list_authenticated_room_players", lambda _room_id, exclude_client_id=None: [])
    monkeypatch.setattr(display_room, "list_room_corpses", lambda _session, _room_id: [])
    monkeypatch.setattr(display_room, "is_entity_hostile_to_player", lambda _session, _entity: False)

    outbound = display_room.display_room(viewer, room)
    rendered = _extract_display_text(outbound)

    assert "Sentry (standing)" in rendered
    assert "Bandit (sitting)" in rendered
    assert "Priest (resting)" in rendered


def test_display_room_shows_player_posture_labels(monkeypatch) -> None:
    viewer = _make_session("client-viewer", "Lucia")
    room = Room(room_id="start", title="Start", description="A room.")

    standing_player = _make_session("client-standing", "Ragnar")
    sitting_player = _make_session("client-sitting", "Beatrix")
    sitting_player.is_sitting = True
    resting_player = _make_session("client-resting", "Orlandu")
    resting_player.is_resting = True

    monkeypatch.setattr(display_room, "list_room_entities", lambda _session, _room_id: [])
    monkeypatch.setattr(
        display_room,
        "list_authenticated_room_players",
        lambda _room_id, exclude_client_id=None: [standing_player, sitting_player, resting_player],
    )
    monkeypatch.setattr(display_room, "list_room_corpses", lambda _session, _room_id: [])

    outbound = display_room.display_room(viewer, room)
    rendered = _extract_display_text(outbound)

    assert "Ragnar (standing)" in rendered
    assert "Beatrix (sitting)" in rendered
    assert "Orlandu (resting)" in rendered
