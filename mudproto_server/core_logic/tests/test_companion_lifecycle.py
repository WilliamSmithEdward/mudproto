from command_handlers.social import _build_group_status_parts
from companions import (
    collect_stray_companion_moves,
    move_companions_with_owner,
    respawn_roster_companions,
)
from death import handle_player_death
from models import ClientSession, EntityState
from player_state_db import load_player_state, save_player_state
from protocol import utc_now_iso
from session_bootstrap import apply_player_class
from session_lifecycle import _copy_runtime_state
from session_registry import active_character_sessions, connected_clients, shared_world_entities


def _make_session(client_id: str, name: str) -> ClientSession:
    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    session.entities = shared_world_entities
    return session


def _make_companion(owner_key: str, *, entity_id: str = "companion-test", room_id: str = "start") -> EntityState:
    companion = EntityState(
        entity_id=entity_id,
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
    companion.max_vigor = 60
    companion.vigor = 60
    companion.spawn_sequence = 50
    return companion


def test_companion_roster_round_trips_through_player_state() -> None:
    session = _make_session("roster-save-client", "Rostersaver")
    session.companion_roster = [{"npc_id": "npc.companion-squire", "name": "Bramble Squire"}]
    save_player_state(session)

    loaded = _make_session("roster-load-client", "Rostersaver")
    loaded.companion_roster = []
    assert load_player_state(loaded) is True
    assert loaded.companion_roster == [{"npc_id": "npc.companion-squire", "name": "Bramble Squire"}]


def test_copy_runtime_state_transfers_companion_roster() -> None:
    source = _make_session("takeover-source", "Takeovertester")
    source.companion_roster = [{"npc_id": "npc.companion-squire", "name": "Bramble Squire"}]
    target = _make_session("takeover-target", "Takeovertester")

    _copy_runtime_state(source, target)

    assert target.companion_roster == source.companion_roster
    assert target.companion_roster is not source.companion_roster


def test_respawn_roster_companions_is_idempotent() -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        session = _make_session("respawn-client", "Respawntester")
        session.companion_roster = [{"npc_id": "npc.companion-squire", "name": "Bramble Squire"}]

        spawned_first = respawn_roster_companions(session)
        spawned_second = respawn_roster_companions(session)

        assert len(spawned_first) == 1
        assert spawned_second == []
        live_companions = [entity for entity in shared_world_entities.values() if entity.is_companion]
        assert len(live_companions) == 1
        assert live_companions[0].owner_player_key == "respawntester"
        assert live_companions[0].room_id == "start"
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_player_death_despawns_companions_but_keeps_roster() -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        session = _make_session("death-client", "Deathtester")
        session.companion_roster = [{"npc_id": "npc.companion-squire", "name": "Bramble Squire"}]
        companion = _make_companion("deathtester")
        shared_world_entities[companion.entity_id] = companion

        handle_player_death(session)

        assert companion.entity_id not in shared_world_entities
        assert session.companion_roster == [{"npc_id": "npc.companion-squire", "name": "Bramble Squire"}]
        assert session.pending_death_logout is True
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_move_companions_with_owner_relocates_room_companions() -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        session = _make_session("move-client", "Movetester")
        companion = _make_companion("movetester")
        shared_world_entities[companion.entity_id] = companion

        moved = move_companions_with_owner(session, "start", "hall")

        assert [entity.entity_id for entity in moved] == [companion.entity_id]
        assert companion.room_id == "hall"
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_leash_returns_stray_companions_to_owner_room() -> None:
    previous_entities = dict(shared_world_entities)
    previous_connected = dict(connected_clients)
    previous_active = dict(active_character_sessions)
    try:
        shared_world_entities.clear()
        connected_clients.clear()
        active_character_sessions.clear()

        owner = _make_session("leash-client", "Leashtester")
        owner.player.current_room_id = "hall"
        connected_clients[owner.client_id] = owner

        stray = _make_companion("leashtester", entity_id="companion-stray", room_id="start")
        orphan = _make_companion("nobody", entity_id="companion-orphan", room_id="start")
        shared_world_entities[stray.entity_id] = stray
        shared_world_entities[orphan.entity_id] = orphan

        moves = collect_stray_companion_moves()

        assert [(entity.entity_id, from_room, to_room) for entity, from_room, to_room in moves] == [
            ("companion-stray", "start", "hall"),
        ]
        assert stray.room_id == "hall"
        assert orphan.entity_id not in shared_world_entities
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)
        connected_clients.clear()
        connected_clients.update(previous_connected)
        active_character_sessions.clear()
        active_character_sessions.update(previous_active)


def test_group_status_shows_kind_column_with_human_and_ai_rows() -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        session = _make_session("group-kind-client", "Groupkindtester")
        apply_player_class(session, "class.monk", roll_attributes=True, initialize_progression=True)
        companion = _make_companion("groupkindtester")
        shared_world_entities[companion.entity_id] = companion

        parts = _build_group_status_parts(session)
        rendered = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))

        assert "Kind" in rendered
        assert "Human" in rendered
        assert "AI" in rendered
        assert "Groupkindtester" in rendered
        assert "Bramble Squire" in rendered
        assert "Companion" in rendered
        assert "140/140" in rendered
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_leash_moves_companion_even_while_owner_is_engaged() -> None:
    previous_entities = dict(shared_world_entities)
    previous_connected = dict(connected_clients)
    previous_active = dict(active_character_sessions)
    try:
        shared_world_entities.clear()
        connected_clients.clear()
        active_character_sessions.clear()

        owner = _make_session("engaged-leash-client", "Engagedleasher")
        owner.player.current_room_id = "hall"
        owner.combat.engaged_entity_ids.add("some-enemy")
        connected_clients[owner.client_id] = owner

        stray = _make_companion("engagedleasher", entity_id="companion-engaged-stray", room_id="start")
        shared_world_entities[stray.entity_id] = stray

        moves = collect_stray_companion_moves()

        assert len(moves) == 1
        assert stray.room_id == "hall"
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)
        connected_clients.clear()
        connected_clients.update(previous_connected)
        active_character_sessions.clear()
        active_character_sessions.update(previous_active)


def test_leash_keeps_companions_of_offline_processed_characters() -> None:
    previous_entities = dict(shared_world_entities)
    previous_connected = dict(connected_clients)
    previous_active = dict(active_character_sessions)
    try:
        shared_world_entities.clear()
        connected_clients.clear()
        active_character_sessions.clear()

        offline_owner = _make_session("offline-leash-client", "Offlineleasher")
        offline_owner.is_connected = False
        offline_owner.disconnected_by_server = True
        active_character_sessions["offlineleasher"] = offline_owner

        companion = _make_companion("offlineleasher", entity_id="companion-offline-owner")
        shared_world_entities[companion.entity_id] = companion

        collect_stray_companion_moves()

        assert companion.entity_id in shared_world_entities
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)
        connected_clients.clear()
        connected_clients.update(previous_connected)
        active_character_sessions.clear()
        active_character_sessions.update(previous_active)


def test_companion_defeat_persists_roster_removal(monkeypatch) -> None:
    import player_state_db
    from companions import handle_companion_defeat

    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        session = _make_session("defeat-save-client", "Defeatsaver")
        session.companion_roster = [{"npc_id": "npc.companion-squire", "name": "Bramble Squire"}]
        companion = _make_companion("defeatsaver")
        shared_world_entities[companion.entity_id] = companion

        saved_sessions: list[str] = []
        monkeypatch.setattr(
            player_state_db,
            "save_player_state",
            lambda sess, player_key=None: saved_sessions.append(sess.player_state_key),
        )

        handle_companion_defeat(session, companion)

        assert session.companion_roster == []
        assert saved_sessions == ["defeatsaver"]
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)
