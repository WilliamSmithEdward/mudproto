import combat
import combat_state
import command_handlers.world as world_handler
import asyncio

from models import ClientSession, EntityState
from settings import COMBAT_ROUND_INTERVAL_SECONDS
from session_registry import shared_world_entities


def _make_session(client_id: str, name: str = "Tester") -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    return session


def _make_entity(entity_id: str = "entity-dummy", name: str = "Dummy") -> EntityState:
    return EntityState(
        entity_id=entity_id,
        name=name,
        room_id="start",
        hit_points=20,
        max_hit_points=20,
    )


def test_begin_attack_applies_one_round_lag_on_success(monkeypatch) -> None:
    session = _make_session("client-begin")
    target = _make_entity()

    lag_calls: list[float] = []

    monkeypatch.setattr(combat, "clear_combat_if_invalid", lambda _session: None)
    monkeypatch.setattr(
        combat,
        "resolve_room_entity_selector",
        lambda _session, _room_id, _target_name, living_only=True: (target, None),
    )
    monkeypatch.setattr(combat, "start_combat", lambda _session, _entity_id, _opener: True)
    monkeypatch.setattr(combat, "resolve_combat_round", lambda _session: {"type": "display", "payload": {"lines": []}})
    monkeypatch.setattr(combat, "apply_lag", lambda _session, seconds: lag_calls.append(seconds))

    result = combat.begin_attack(session, "dummy")

    assert isinstance(result, list)
    assert lag_calls == [COMBAT_ROUND_INTERVAL_SECONDS]


def test_begin_attack_does_not_apply_lag_when_engagement_fails(monkeypatch) -> None:
    session = _make_session("client-begin-fail")
    target = _make_entity()

    lag_calls: list[float] = []

    monkeypatch.setattr(combat, "clear_combat_if_invalid", lambda _session: None)
    monkeypatch.setattr(
        combat,
        "resolve_room_entity_selector",
        lambda _session, _room_id, _target_name, living_only=True: (target, None),
    )
    monkeypatch.setattr(combat, "start_combat", lambda _session, _entity_id, _opener: False)
    monkeypatch.setattr(combat, "apply_lag", lambda _session, seconds: lag_calls.append(seconds))

    result = combat.begin_attack(session, "dummy")

    assert isinstance(result, dict)
    assert lag_calls == []


def test_assist_applies_one_round_lag_on_success(monkeypatch) -> None:
    session = _make_session("client-assist", name="Lucia")
    helper = _make_session("client-helper", name="Orlandu")
    target = _make_entity(entity_id="entity-scout", name="Hall Scout")

    lag_calls: list[float] = []

    monkeypatch.setattr(world_handler, "start_combat", lambda _session, _entity_id, _opener, trigger_player_auto_aggro=False: True)
    monkeypatch.setattr(world_handler, "resolve_combat_round", lambda _session: {"type": "display", "payload": {"lines": []}})
    monkeypatch.setattr(world_handler, "apply_lag", lambda _session, seconds: lag_calls.append(seconds))

    result = world_handler._assist_on_entity(session, assisted_session=helper, target_entity=target)

    assert isinstance(result, list)
    assert lag_calls == [COMBAT_ROUND_INTERVAL_SECONDS]


def test_assist_does_not_apply_lag_when_start_combat_fails(monkeypatch) -> None:
    session = _make_session("client-assist-fail", name="Lucia")
    helper = _make_session("client-helper-fail", name="Orlandu")
    target = _make_entity(entity_id="entity-scout", name="Hall Scout")

    lag_calls: list[float] = []

    monkeypatch.setattr(world_handler, "start_combat", lambda _session, _entity_id, _opener, trigger_player_auto_aggro=False: False)
    monkeypatch.setattr(world_handler, "apply_lag", lambda _session, seconds: lag_calls.append(seconds))

    result = world_handler._assist_on_entity(session, assisted_session=helper, target_entity=target)

    assert isinstance(result, dict)
    assert lag_calls == []


def test_npc_auto_aggro_applies_one_round_lag_on_success(monkeypatch) -> None:
    async def _run() -> None:
        session = _make_session("client-npc-aggro", name="Lucia")
        entity = _make_entity(entity_id="entity-auto", name="Auto Aggro Dummy")

        lag_calls: list[float] = []
        previous_entities = dict(shared_world_entities)
        previous_pending = dict(combat_state._pending_auto_aggro_due_monotonic)

        now = asyncio.get_running_loop().time()
        shared_world_entities.clear()
        shared_world_entities[entity.entity_id] = entity
        combat_state._pending_auto_aggro_due_monotonic.clear()
        combat_state._pending_auto_aggro_due_monotonic[entity.entity_id] = now - 1.0

        monkeypatch.setattr(combat_state, "_get_entity_engaged_sessions", lambda _entity: [])
        monkeypatch.setattr(combat_state, "_list_valid_auto_aggro_targets_for_entity", lambda _entity: [session])
        monkeypatch.setattr(combat_state.random, "choice", lambda candidates: candidates[0])
        monkeypatch.setattr(combat_state, "start_combat", lambda _session, _entity_id, _opening: True)
        monkeypatch.setattr(combat_state, "apply_lag", lambda _session, seconds: lag_calls.append(seconds))

        try:
            combat_state.process_pending_auto_aggro()
        finally:
            shared_world_entities.clear()
            shared_world_entities.update(previous_entities)
            combat_state._pending_auto_aggro_due_monotonic.clear()
            combat_state._pending_auto_aggro_due_monotonic.update(previous_pending)

        assert lag_calls == [COMBAT_ROUND_INTERVAL_SECONDS]

    asyncio.run(_run())
