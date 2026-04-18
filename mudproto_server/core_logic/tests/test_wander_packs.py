from __future__ import annotations

import asyncio

import server_loops
from models import EntityState
from session_registry import shared_world_entities
from world import WORLD, Room


def _make_entity(entity_id: str, name: str, room_id: str, *, wander_chance: float = 1.0,
                 wander_room_ids: list[str] | None = None, wander_pack_id: str = "") -> EntityState:
    entity = EntityState(
        entity_id=entity_id,
        name=name,
        room_id=room_id,
        hit_points=100,
        max_hit_points=100,
    )
    entity.wander_chance = wander_chance
    entity.wander_room_ids = wander_room_ids or []
    entity.wander_pack_id = wander_pack_id
    return entity


def _install_rooms(rooms: dict[str, Room]) -> None:
    WORLD.rooms.update(rooms)


def _uninstall_rooms(room_ids: list[str]) -> None:
    for rid in room_ids:
        WORLD.rooms.pop(rid, None)


def _setup(monkeypatch):
    shared_world_entities.clear()
    monkeypatch.setattr(server_loops, "_iter_room_sessions", lambda _room_id: [])

    async def _fake_send_outbound(_websocket, _outbound):
        return True

    monkeypatch.setattr(server_loops, "send_outbound", _fake_send_outbound)


def test_pack_members_move_together(monkeypatch) -> None:
    _setup(monkeypatch)
    room_ids = ["room-a", "room-b"]
    _install_rooms({
        "room-a": Room(room_id="room-a", title="Room A", description="", zone_id="z", exits={"east": "room-b"}),
        "room-b": Room(room_id="room-b", title="Room B", description="", zone_id="z", exits={"west": "room-a"}),
    })

    alpha = _make_entity("npc-alpha", "Wolf", "room-a",
                         wander_room_ids=["room-a", "room-b"], wander_pack_id="wolf-pack")
    beta = _make_entity("npc-beta", "Wolf", "room-a",
                        wander_room_ids=["room-a", "room-b"], wander_pack_id="wolf-pack")

    shared_world_entities[alpha.entity_id] = alpha
    shared_world_entities[beta.entity_id] = beta

    monkeypatch.setattr(server_loops.random, "random", lambda: 0.0)
    monkeypatch.setattr(server_loops.random, "choice", lambda candidates: candidates[0])

    try:
        asyncio.run(server_loops._process_npc_wandering())
        assert alpha.room_id == "room-b"
        assert beta.room_id == "room-b", "Pack member should move with the leader"
    finally:
        shared_world_entities.clear()
        _uninstall_rooms(room_ids)


def test_pack_member_in_different_room_is_not_dragged(monkeypatch) -> None:
    _setup(monkeypatch)
    room_ids = ["room-a", "room-b", "room-c"]
    _install_rooms({
        "room-a": Room(room_id="room-a", title="Room A", description="", zone_id="z", exits={"east": "room-b"}),
        "room-b": Room(room_id="room-b", title="Room B", description="", zone_id="z", exits={"west": "room-a", "east": "room-c"}),
        "room-c": Room(room_id="room-c", title="Room C", description="", zone_id="z", exits={"west": "room-b"}),
    })

    alpha = _make_entity("npc-alpha", "Wolf", "room-a",
                         wander_room_ids=["room-a", "room-b", "room-c"], wander_pack_id="wolf-pack")
    beta = _make_entity("npc-beta", "Wolf", "room-b",
                        wander_room_ids=["room-a", "room-b", "room-c"], wander_pack_id="wolf-pack")

    shared_world_entities[alpha.entity_id] = alpha
    shared_world_entities[beta.entity_id] = beta

    monkeypatch.setattr(server_loops.random, "random", lambda: 0.0)
    monkeypatch.setattr(server_loops.random, "choice", lambda candidates: candidates[0])

    try:
        asyncio.run(server_loops._process_npc_wandering())
        # Alpha moves from room-a → room-b; beta is in room-b (different room at decision time), so
        # beta makes its own independent wander from room-b.
        assert alpha.room_id == "room-b"
        assert beta.room_id != "room-b" or beta.room_id == "room-a", \
            "Beta should have wandered independently from room-b"
    finally:
        shared_world_entities.clear()
        _uninstall_rooms(room_ids)


def test_engaged_pack_member_left_behind(monkeypatch) -> None:
    _setup(monkeypatch)
    room_ids = ["room-a", "room-b"]
    _install_rooms({
        "room-a": Room(room_id="room-a", title="Room A", description="", zone_id="z", exits={"east": "room-b"}),
        "room-b": Room(room_id="room-b", title="Room B", description="", zone_id="z", exits={"west": "room-a"}),
    })

    alpha = _make_entity("npc-alpha", "Wolf", "room-a",
                         wander_room_ids=["room-a", "room-b"], wander_pack_id="wolf-pack")
    beta = _make_entity("npc-beta", "Wolf", "room-a",
                        wander_room_ids=["room-a", "room-b"], wander_pack_id="wolf-pack")

    shared_world_entities[alpha.entity_id] = alpha
    shared_world_entities[beta.entity_id] = beta

    original_engaged = server_loops._entity_is_engaged_by_any_player
    monkeypatch.setattr(server_loops, "_entity_is_engaged_by_any_player",
                        lambda eid: eid == "npc-beta" or original_engaged(eid))

    monkeypatch.setattr(server_loops.random, "random", lambda: 0.0)
    monkeypatch.setattr(server_loops.random, "choice", lambda candidates: candidates[0])

    try:
        asyncio.run(server_loops._process_npc_wandering())
        assert alpha.room_id == "room-b", "Non-engaged pack member should wander"
        assert beta.room_id == "room-a", "Engaged pack member should be left behind"
    finally:
        shared_world_entities.clear()
        _uninstall_rooms(room_ids)


def test_no_pack_id_wander_independently(monkeypatch) -> None:
    _setup(monkeypatch)
    room_ids = ["room-a", "room-b", "room-c"]
    _install_rooms({
        "room-a": Room(room_id="room-a", title="Room A", description="", zone_id="z", exits={"east": "room-b", "west": "room-c"}),
        "room-b": Room(room_id="room-b", title="Room B", description="", zone_id="z", exits={"west": "room-a"}),
        "room-c": Room(room_id="room-c", title="Room C", description="", zone_id="z", exits={"east": "room-a"}),
    })

    alpha = _make_entity("npc-alpha", "Bandit", "room-a",
                         wander_room_ids=["room-a", "room-b", "room-c"])
    beta = _make_entity("npc-beta", "Bandit", "room-a",
                        wander_room_ids=["room-a", "room-b", "room-c"])

    shared_world_entities[alpha.entity_id] = alpha
    shared_world_entities[beta.entity_id] = beta

    call_count = 0

    def _alternating_choice(candidates):
        nonlocal call_count
        pick = candidates[call_count % len(candidates)]
        call_count += 1
        return pick

    monkeypatch.setattr(server_loops.random, "random", lambda: 0.0)
    monkeypatch.setattr(server_loops.random, "choice", _alternating_choice)

    try:
        asyncio.run(server_loops._process_npc_wandering())
        assert alpha.room_id != "room-a"
        assert beta.room_id != "room-a"
    finally:
        shared_world_entities.clear()
        _uninstall_rooms(room_ids)


def test_different_pack_ids_wander_separately(monkeypatch) -> None:
    _setup(monkeypatch)
    room_ids = ["room-a", "room-b", "room-c"]
    _install_rooms({
        "room-a": Room(room_id="room-a", title="Room A", description="", zone_id="z", exits={"east": "room-b", "west": "room-c"}),
        "room-b": Room(room_id="room-b", title="Room B", description="", zone_id="z", exits={"west": "room-a"}),
        "room-c": Room(room_id="room-c", title="Room C", description="", zone_id="z", exits={"east": "room-a"}),
    })

    alpha = _make_entity("npc-alpha", "Wolf", "room-a",
                         wander_room_ids=["room-a", "room-b", "room-c"], wander_pack_id="wolves")
    beta = _make_entity("npc-beta", "Bear", "room-a",
                        wander_room_ids=["room-a", "room-b", "room-c"], wander_pack_id="bears")

    shared_world_entities[alpha.entity_id] = alpha
    shared_world_entities[beta.entity_id] = beta

    call_count = 0

    def _alternating_choice(candidates):
        nonlocal call_count
        pick = candidates[call_count % len(candidates)]
        call_count += 1
        return pick

    monkeypatch.setattr(server_loops.random, "random", lambda: 0.0)
    monkeypatch.setattr(server_loops.random, "choice", _alternating_choice)

    try:
        asyncio.run(server_loops._process_npc_wandering())
        assert alpha.room_id != "room-a"
        assert beta.room_id != "room-a"
    finally:
        shared_world_entities.clear()
        _uninstall_rooms(room_ids)


def test_dead_pack_member_not_moved(monkeypatch) -> None:
    _setup(monkeypatch)
    room_ids = ["room-a", "room-b"]
    _install_rooms({
        "room-a": Room(room_id="room-a", title="Room A", description="", zone_id="z", exits={"east": "room-b"}),
        "room-b": Room(room_id="room-b", title="Room B", description="", zone_id="z", exits={"west": "room-a"}),
    })

    alpha = _make_entity("npc-alpha", "Wolf", "room-a",
                         wander_room_ids=["room-a", "room-b"], wander_pack_id="wolf-pack")
    beta = _make_entity("npc-beta", "Wolf", "room-a",
                        wander_room_ids=["room-a", "room-b"], wander_pack_id="wolf-pack")
    beta.is_alive = False

    shared_world_entities[alpha.entity_id] = alpha
    shared_world_entities[beta.entity_id] = beta

    monkeypatch.setattr(server_loops.random, "random", lambda: 0.0)
    monkeypatch.setattr(server_loops.random, "choice", lambda candidates: candidates[0])

    try:
        asyncio.run(server_loops._process_npc_wandering())
        assert alpha.room_id == "room-b"
        assert beta.room_id == "room-a", "Dead pack member should not be moved"
    finally:
        shared_world_entities.clear()
        _uninstall_rooms(room_ids)
