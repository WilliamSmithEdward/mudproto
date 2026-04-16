from commerce import _display_merchant_stock
from protocol import utc_now_iso
from models import ClientSession, EntityState
from session_registry import active_character_sessions, connected_clients, shared_world_entities
from world_population import initialize_session_entities, initialize_shared_world_state, repopulate_game_hour_zones, reinitialize_zone
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

        spawned_count = reinitialize_zone("zone.northern-wing", force=True)

        assert spawned_count >= 2
        assert aggro_checks == [occupant.client_id]
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)
        connected_clients.clear()
        connected_clients.update(previous_connected)
        active_character_sessions.clear()
        active_character_sessions.update(previous_active)


def test_merchant_stock_display_shows_equipment_slot_labels() -> None:
    session = _make_session("merchant-display-client")
    session.player.current_room_id = "south-market"

    merchant = EntityState(
        entity_id="merchant-wares",
        name="Quartermaster Vessa",
        room_id="south-market",
        hit_points=100,
        max_hit_points=100,
    )
    merchant.is_alive = True
    merchant.is_merchant = True
    merchant.merchant_inventory = [
        {"template_id": "item.potion.mending", "infinite": True, "quantity": 3, "base_quantity": 3},
        {"template_id": "weapon.training-sword", "infinite": True, "quantity": 1, "base_quantity": 1},
        {"template_id": "armor.vanguard-jacket", "infinite": True, "quantity": 1, "base_quantity": 1},
    ]

    outbound = _display_merchant_stock(session, merchant)
    lines = [
        "".join(str(part.get("text", "")) for part in line if isinstance(part, dict))
        for line in outbound.get("payload", {}).get("lines", [])
        if isinstance(line, list)
    ]
    rendered = "\n".join(lines)

    assert "Potion of Mending" in rendered and "Potion" in rendered
    assert "Training Sword" in rendered and "Weapon" in rendered
    assert "Vanguard Jacket" in rendered and "Chest" in rendered


def test_repopulate_game_hour_zones_blocks_when_current_session_is_in_zone_even_if_stale_duplicate_exists(monkeypatch) -> None:
    previous_connected = dict(connected_clients)
    previous_active = dict(active_character_sessions)
    try:
        connected_clients.clear()
        active_character_sessions.clear()

        zone = world_population.WORLD.zones["zone.northern-wing"]
        original_pending = zone.pending_repopulation
        original_hours = zone.game_hours_since_repopulation
        original_block = zone.repopulation_block_remaining_hours

        zone.pending_repopulation = True
        zone.game_hours_since_repopulation = zone.repopulate_game_hours
        zone.repopulation_block_remaining_hours = 0

        stale_session = _make_session("stale-client")
        stale_session.is_authenticated = True
        stale_session.player_state_key = "lucia"
        stale_session.player.current_room_id = "start"

        current_session = _make_session("current-client")
        current_session.is_authenticated = True
        current_session.player_state_key = "lucia"
        current_session.player.current_room_id = "hall"

        active_character_sessions["lucia"] = stale_session
        connected_clients[current_session.client_id] = current_session

        repopulated_zone_ids: list[str] = []
        monkeypatch.setattr(world_population, "reinitialize_zone", lambda zone_id: repopulated_zone_ids.append(zone_id) or 0)

        repopulate_game_hour_zones()

        assert "zone.northern-wing" not in repopulated_zone_ids
        assert zone.pending_repopulation is True
    finally:
        zone = world_population.WORLD.zones["zone.northern-wing"]
        zone.pending_repopulation = original_pending
        zone.game_hours_since_repopulation = original_hours
        zone.repopulation_block_remaining_hours = original_block
        connected_clients.clear()
        connected_clients.update(previous_connected)
        active_character_sessions.clear()
        active_character_sessions.update(previous_active)


def test_reinitialize_zone_noops_when_authenticated_player_is_still_inside() -> None:
    previous_entities = dict(shared_world_entities)
    previous_connected = dict(connected_clients)
    previous_active = dict(active_character_sessions)
    try:
        shared_world_entities.clear()
        connected_clients.clear()
        active_character_sessions.clear()

        occupant = _make_session("occupied-client")
        occupant.is_authenticated = True
        occupant.player_state_key = "occupant"
        occupant.player.current_room_id = "hall"
        connected_clients[occupant.client_id] = occupant
        active_character_sessions[occupant.player_state_key] = occupant

        existing = EntityState(
            entity_id="existing-scout",
            name="Existing Scout",
            room_id="hall",
            hit_points=10,
            max_hit_points=10,
        )
        existing.npc_id = "npc.hall-scout"
        existing.is_alive = True
        existing.respawn = True
        shared_world_entities[existing.entity_id] = existing

        spawned_count = reinitialize_zone("zone.northern-wing")

        assert spawned_count == 0
        assert list(shared_world_entities) == ["existing-scout"]
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)
        connected_clients.clear()
        connected_clients.update(previous_connected)
        active_character_sessions.clear()
        active_character_sessions.update(previous_active)
