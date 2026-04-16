from protocol import utc_now_iso
from models import ClientSession, EntityState
from session_registry import shared_world_entities
from world_population import initialize_session_entities


def _make_session(client_id: str = "test-client") -> ClientSession:
    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_connected = True
    session.entities = shared_world_entities
    return session


def test_initialize_session_entities_restores_missing_market_merchant_when_world_already_exists() -> None:
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

        session = _make_session()
        initialize_session_entities(session)

        merchant_ids = [
            getattr(entity, "npc_id", "")
            for entity in shared_world_entities.values()
            if getattr(entity, "room_id", "") == "south-market"
        ]
        assert "npc.south-market-merchant" in merchant_ids
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_initialize_session_entities_does_not_duplicate_market_merchant() -> None:
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

        session = _make_session("test-client-2")
        initialize_session_entities(session)

        merchant_ids = [
            entity_id
            for entity_id, entity in shared_world_entities.items()
            if getattr(entity, "npc_id", "") == "npc.south-market-merchant"
        ]
        assert merchant_ids == ["merchant-1"]
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)
