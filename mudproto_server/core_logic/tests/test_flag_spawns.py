"""Smoke-tests for the flag_spawns mechanic.

Exercises the full path from apply_entity_defeat_flags → process_zone_flag_spawns.
Path setup is handled by conftest.py.
"""
import asyncio
from typing import Any, cast

import pytest

import world_population
from combat_state import apply_entity_defeat_flags
from models import ClientSession, CombatState, EntityState, PlayerState, PlayerStatus
from session_registry import active_character_sessions, connected_clients, shared_world_entities, shared_world_flags
from world import WORLD, Zone
from world_population import process_zone_flag_spawns

# ── helpers ────────────────────────────────────────────────────────────────

_ROOM_ID = next(iter(WORLD.rooms))  # first real room in the world


def _make_session() -> ClientSession:
    from protocol import utc_now_iso
    session = ClientSession(client_id="test-client", websocket=None, connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.entities = shared_world_entities
    session.is_authenticated = True
    session.is_connected = True
    session.player = PlayerState(current_room_id=_ROOM_ID, class_id="", level=1)
    session.status = PlayerStatus()
    session.combat = CombatState()
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


def _make_entity(entity_id: str, npc_id: str, *, death_flags: list[str] | None = None) -> EntityState:
    e = EntityState(entity_id=entity_id, name="Test NPC", room_id=_ROOM_ID, hit_points=0, max_hit_points=100)
    e.npc_id = npc_id
    e.is_alive = True
    e.set_world_flags_on_death = death_flags or []
    e.set_player_flags_on_death = []
    return e


def _inject_zone(zone_id: str, flag_spawns: list[dict]) -> None:
    zone = Zone(zone_id=zone_id, name="Test Zone", repopulate_game_hours=0)
    zone.room_ids = [_ROOM_ID]
    zone.flag_spawns = flag_spawns
    WORLD.zones[zone_id] = zone


def _patch_npc_template(npc_id: str) -> None:
    """Patch world_population.get_npc_template_by_id for a fake NPC."""
    original = world_population.get_npc_template_by_id

    def _patched(tid: str) -> dict | None:
        if tid == npc_id:
            return {"npc_id": npc_id, "name": "Big Boss", "hit_points": 500, "max_hit_points": 500, "respawn": False}
        return original(tid)

    world_population.get_npc_template_by_id = _patched


@pytest.fixture(autouse=True)
def _clean_world_state():
    """Clear test entities and flags before and after every test."""
    def _purge():
        shared_world_flags.clear()
        connected_clients.clear()
        active_character_sessions.clear()
        for eid in [k for k in shared_world_entities if k.startswith("test-")]:
            shared_world_entities.pop(eid, None)
        for zid in [k for k in WORLD.zones if k.startswith("zone.test-")]:
            WORLD.zones.pop(zid, None)

    _purge()
    yield
    _purge()


# ── tests ──────────────────────────────────────────────────────────────────

def test_boss_spawns_when_miniboss_dies() -> None:
    ZONE_ID = "zone.test-flag-spawn"
    MINI_NPC_ID = "npc.test-miniboss"
    BOSS_NPC_ID = "npc.test-bigboss"
    DEATH_FLAG = "flag.test-miniboss-slain"

    _inject_zone(ZONE_ID, [{"npc_id": BOSS_NPC_ID, "room_id": _ROOM_ID, "count": 1,
                             "required_world_flags": [DEATH_FLAG], "excluded_world_flags": []}])
    _patch_npc_template(BOSS_NPC_ID)

    mini_boss = _make_entity("test-miniboss-1", MINI_NPC_ID, death_flags=[DEATH_FLAG])
    shared_world_entities["test-miniboss-1"] = mini_boss

    assert not any(getattr(e, "npc_id", "") == BOSS_NPC_ID for e in shared_world_entities.values())

    apply_entity_defeat_flags(_make_session(), mini_boss)

    assert DEATH_FLAG in shared_world_flags
    alive_bosses = [e for e in shared_world_entities.values()
                    if getattr(e, "npc_id", "") == BOSS_NPC_ID and getattr(e, "is_alive", False)]
    assert len(alive_bosses) == 1


def test_no_duplicate_when_boss_already_alive() -> None:
    ZONE_ID = "zone.test-flag-spawn-dedup"
    MINI_NPC_ID = "npc.test-miniboss-2"
    BOSS_NPC_ID = "npc.test-bigboss-2"
    DEATH_FLAG = "flag.test-miniboss-2-slain"

    _inject_zone(ZONE_ID, [{"npc_id": BOSS_NPC_ID, "room_id": _ROOM_ID, "count": 1,
                             "required_world_flags": [DEATH_FLAG], "excluded_world_flags": []}])
    _patch_npc_template(BOSS_NPC_ID)

    existing_boss = _make_entity("test-existing-boss", BOSS_NPC_ID)
    existing_boss.is_alive = True
    shared_world_entities["test-existing-boss"] = existing_boss

    mini_boss = _make_entity("test-miniboss-2", MINI_NPC_ID, death_flags=[DEATH_FLAG])
    shared_world_entities["test-miniboss-2"] = mini_boss

    apply_entity_defeat_flags(_make_session(), mini_boss)

    alive_bosses = [e for e in shared_world_entities.values()
                    if getattr(e, "npc_id", "") == BOSS_NPC_ID and getattr(e, "is_alive", False)]
    assert len(alive_bosses) == 1


def test_spawn_suppressed_by_excluded_flag() -> None:
    ZONE_ID = "zone.test-flag-spawn-excl"
    MINI_NPC_ID = "npc.test-miniboss-3"
    BOSS_NPC_ID = "npc.test-bigboss-3"
    DEATH_FLAG = "flag.test-miniboss-3-slain"
    EXCLUDE_FLAG = "flag.test-suppress"

    _inject_zone(ZONE_ID, [{"npc_id": BOSS_NPC_ID, "room_id": _ROOM_ID, "count": 1,
                             "required_world_flags": [DEATH_FLAG], "excluded_world_flags": [EXCLUDE_FLAG]}])
    _patch_npc_template(BOSS_NPC_ID)
    shared_world_flags.add(EXCLUDE_FLAG)

    mini_boss = _make_entity("test-miniboss-3", MINI_NPC_ID, death_flags=[DEATH_FLAG])
    shared_world_entities["test-miniboss-3"] = mini_boss

    apply_entity_defeat_flags(_make_session(), mini_boss)

    alive_bosses = [e for e in shared_world_entities.values()
                    if getattr(e, "npc_id", "") == BOSS_NPC_ID and getattr(e, "is_alive", False)]
    assert len(alive_bosses) == 0


def test_no_spawn_without_required_flag() -> None:
    ZONE_ID = "zone.test-flag-spawn-noflag"
    BOSS_NPC_ID = "npc.test-bigboss-4"

    _inject_zone(ZONE_ID, [{"npc_id": BOSS_NPC_ID, "room_id": _ROOM_ID, "count": 1,
                             "required_world_flags": ["flag.nonexistent"], "excluded_world_flags": []}])
    _patch_npc_template(BOSS_NPC_ID)

    process_zone_flag_spawns()

    assert not any(getattr(e, "npc_id", "") == BOSS_NPC_ID for e in shared_world_entities.values())


def test_crowbanner_final_boss_is_flag_gated() -> None:
    zone = WORLD.zones["zone.crowbanner-fort-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11"]
    north_yard = WORLD.rooms["room.north-yard-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11"]

    assert "north" not in north_yard.exits

    matching_rules = [
        rule for rule in getattr(zone, "flag_spawns", [])
        if rule.get("npc_id") == "npc.hadrik-crowbanner-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11"
    ]
    assert len(matching_rules) == 1
    assert set(matching_rules[0].get("required_world_flags", [])) == {
        "npc.ironhook-maela.defeated",
        "npc.varo-cindersmile.defeated",
        "npc.seln-of-the-pins.defeated",
        "npc.brother-cleft.defeated",
    }


def test_flag_spawn_announcement_notifies_zone_players(monkeypatch) -> None:
    zone_id = "zone.test-flag-spawn-announce"
    mini_npc_id = "npc.test-miniboss-announce"
    boss_npc_id = "npc.test-bigboss-announce"
    death_flag = "flag.test-miniboss-announce-slain"

    _inject_zone(zone_id, [{
        "npc_id": boss_npc_id,
        "room_id": _ROOM_ID,
        "count": 1,
        "required_world_flags": [death_flag],
        "excluded_world_flags": [],
        "announcement_message": "A dread horn sounds. The final foe is ready."
    }])
    _patch_npc_template(boss_npc_id)

    session = _make_session()
    session.client_id = "test-zone-player"
    session.websocket = cast(Any, object())
    connected_clients[session.client_id] = session

    notifications: list[tuple[object, dict | list[dict]]] = []

    async def fake_send_outbound(websocket, outbound):
        notifications.append((websocket, outbound))
        return True

    monkeypatch.setattr(world_population, "send_outbound", fake_send_outbound, raising=False)

    mini_boss = _make_entity("test-miniboss-announce", mini_npc_id, death_flags=[death_flag])
    shared_world_entities["test-miniboss-announce"] = mini_boss

    async def _scenario() -> None:
        apply_entity_defeat_flags(session, mini_boss)
        await asyncio.sleep(0)

    asyncio.run(_scenario())

    assert any(websocket is session.websocket for websocket, _outbound in notifications)
    assert any("The final foe is ready." in _extract_display_text(outbound) for _websocket, outbound in notifications)

    display_messages = [
        outbound
        for _websocket, outbound in notifications
        if isinstance(outbound, dict) and outbound.get("type") == "display"
    ]
    assert display_messages

    payload = display_messages[0].get("payload")
    assert isinstance(payload, dict)

    lines = payload.get("lines")
    assert isinstance(lines, list)
    assert lines[0] == []
    assert "The final foe is ready." in _extract_display_text(display_messages[0])

    prompt_lines = payload.get("prompt_lines")
    assert isinstance(prompt_lines, list)
    assert prompt_lines[0] == []
