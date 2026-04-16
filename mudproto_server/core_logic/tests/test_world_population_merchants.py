from protocol import utc_now_iso
from models import ClientSession, EntityState
from session_registry import active_character_sessions, connected_clients, shared_world_entities
from world_population import initialize_session_entities, initialize_shared_world_state, reinitialize_zone
import world_population


def _make_session(client_id: str = "test-client") -> ClientSession:
    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_connected = True
    session.entities = shared_world_entities
    return session


def test_initialize_shared_world_state_restores_missing_market_merchant() -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        shared_world_entities["existing-npc"] = EntityState(
            entity_id="existing-npc",
            name="Existing Scout",
            room_id="start",
            hit_points=10,
            max_hit_points=10,
        )

        initialize_shared_world_state()

        merchant_ids = [
            getattr(entity, "npc_id", "")
            for entity in shared_world_entities.values()
            if getattr(entity, "room_id", "") == "south-market"
        ]
        assert "npc.south-market-merchant" in merchant_ids
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_initialize_shared_world_state_does_not_duplicate_market_merchant() -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        merchant = EntityState(
            entity_id="merchant-1",
            name="Quartermaster Vessa",
            room_id="south-market",
            hit_points=180,
            max_hit_points=180,
        )
        merchant.npc_id = "npc.south-market-merchant"
        merchant.is_alive = True
        shared_world_entities[merchant.entity_id] = merchant

        initialize_shared_world_state()

        merchant_ids = [
            entity_id
            for entity_id, entity in shared_world_entities.items()
            if getattr(entity, "npc_id", "") == "npc.south-market-merchant"
        ]
        assert merchant_ids == ["merchant-1"]
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_initialize_session_entities_does_not_mutate_shared_world_on_login() -> None:
    previous_entities = dict(shared_world_entities)
    previous_connected = dict(connected_clients)
    previous_active = dict(active_character_sessions)
    try:
        shared_world_entities.clear()
        connected_clients.clear()
        active_character_sessions.clear()

        occupant = _make_session("occupied-client")
        occupant.is_authenticated = True
        occupant.player.current_room_id = "hall"
        connected_clients[occupant.client_id] = occupant
        active_character_sessions[occupant.player_state_key] = occupant

        session = _make_session("login-client")
        initialize_session_entities(session)

        assert shared_world_entities == {}
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)
        connected_clients.clear()
        connected_clients.update(previous_connected)
        active_character_sessions.clear()
        active_character_sessions.update(previous_active)


def test_reinitialize_zone_evaluates_auto_aggro_for_players_in_repopulated_rooms(monkeypatch) -> None:
    previous_entities = dict(shared_world_entities)
    previous_connected = dict(connected_clients)
    previous_active = dict(active_character_sessions)
    try:
        shared_world_entities.clear()
        connected_clients.clear()
        active_character_sessions.clear()

        occupant = _make_session("hall-client")
        occupant.is_authenticated = True
        occupant.player.current_room_id = "hall"
        connected_clients[occupant.client_id] = occupant
        active_character_sessions[occupant.player_state_key] = occupant

        aggro_checks: list[str] = []
        monkeypatch.setattr(world_population, "maybe_auto_engage_current_room", lambda session: aggro_checks.append(session.client_id))

        spawned_count = reinitialize_zone("zone.northern-wing")

        assert spawned_count >= 2
        assert aggro_checks == [occupant.client_id]
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)
        connected_clients.clear()
        connected_clients.update(previous_connected)
        active_character_sessions.clear()
        active_character_sessions.update(previous_active)
