import combat_state
import battle_round_ticks
from combat_state import _process_combat_round_timers
from models import ActiveAffectState, ActiveSupportEffectState, ClientSession


def _make_session(client_id: str, name: str) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    return session


def test_out_of_combat_skill_cooldowns_tick_on_round_interval(monkeypatch) -> None:
    session = _make_session("client-cooldown-out", "Lucia")
    session.combat.skill_cooldowns["skill.bash"] = 3

    class _FakeLoop:
        def __init__(self, now: float):
            self._now = now

        def time(self) -> float:
            return self._now

    fake_loop = _FakeLoop(100.0)
    monkeypatch.setattr(battle_round_ticks.asyncio, "get_running_loop", lambda: fake_loop)

    battle_round_ticks.process_non_combat_battleround_tick(session)
    assert session.combat.skill_cooldowns["skill.bash"] == 3
    assert session.next_non_combat_battleround_tick_monotonic is not None

    fake_loop._now = 100.0 + combat_state.COMBAT_ROUND_INTERVAL_SECONDS
    battle_round_ticks.process_non_combat_battleround_tick(session)

    assert session.combat.skill_cooldowns["skill.bash"] == 2


def test_out_of_combat_skill_cooldowns_catch_up_multiple_rounds(monkeypatch) -> None:
    session = _make_session("client-cooldown-catch-up", "Lucia")
    session.combat.skill_cooldowns["skill.bash"] = 3

    class _FakeLoop:
        def __init__(self, now: float):
            self._now = now

        def time(self) -> float:
            return self._now

    fake_loop = _FakeLoop(200.0)
    monkeypatch.setattr(battle_round_ticks.asyncio, "get_running_loop", lambda: fake_loop)

    battle_round_ticks.process_non_combat_battleround_tick(session)
    fake_loop._now = 200.0 + (combat_state.COMBAT_ROUND_INTERVAL_SECONDS * 3.0)
    battle_round_ticks.process_non_combat_battleround_tick(session)

    assert "skill.bash" not in session.combat.skill_cooldowns
    assert session.next_non_combat_battleround_tick_monotonic is None


def test_in_combat_round_timers_tick_skill_cooldowns() -> None:
    session = _make_session("client-cooldown-in", "Lucia")
    session.combat.skill_cooldowns["skill.bash"] = 3

    _process_combat_round_timers(session, [])

    assert session.combat.skill_cooldowns["skill.bash"] == 2


def test_combat_and_non_combat_battleround_parity(monkeypatch) -> None:
    """Both paths (combat timer and non-combat) must produce identical end state."""

    def _make_session_with_activity(client_id: str) -> ClientSession:
        session = _make_session(client_id, "Parity")
        session.combat.skill_cooldowns["skill.bash"] = 5
        effect = ActiveSupportEffectState(
            spell_id="regen",
            spell_name="Regen",
            support_mode="battle_rounds",
            support_effect="heal",
            support_amount=10,
            remaining_hours=0,
            remaining_rounds=4,
        )
        session.active_support_effects.append(effect)
        return session

    class _FakeLoop:
        def __init__(self, now: float):
            self._now = now

        def time(self) -> float:
            return self._now

    fake_loop = _FakeLoop(300.0)
    monkeypatch.setattr(battle_round_ticks.asyncio, "get_running_loop", lambda: fake_loop)

    n_rounds = 3
    interval = combat_state.COMBAT_ROUND_INTERVAL_SECONDS

    # Non-combat path: advance time to trigger exactly n_rounds via non-combat scheduler.
    session_nc = _make_session_with_activity("client-parity-nc")
    battle_round_ticks.process_non_combat_battleround_tick(session_nc)   # sets due_at = 300 + interval
    fake_loop._now = 300.0 + (interval * n_rounds)
    battle_round_ticks.process_non_combat_battleround_tick(session_nc)

    # Combat path: call _process_combat_round_timers n_rounds times directly.
    session_c = _make_session_with_activity("client-parity-c")
    for _ in range(n_rounds):
        _process_combat_round_timers(session_c, [])

    assert session_c.combat.skill_cooldowns == session_nc.combat.skill_cooldowns
    assert len(session_c.active_support_effects) == len(session_nc.active_support_effects)
    for ec, enc in zip(session_c.active_support_effects, session_nc.active_support_effects):
        assert ec.remaining_rounds == enc.remaining_rounds


def test_non_combat_battleround_scheduler_advances_due_at_by_interval(monkeypatch) -> None:
    session = _make_session("client-scheduler-advance", "Lucia")
    session.combat.skill_cooldowns["skill.bash"] = 5

    class _FakeLoop:
        def __init__(self, now: float):
            self._now = now

        def time(self) -> float:
            return self._now

    fake_loop = _FakeLoop(400.0)
    monkeypatch.setattr(battle_round_ticks.asyncio, "get_running_loop", lambda: fake_loop)

    battle_round_ticks.process_non_combat_battleround_tick(session)
    first_due_at = session.next_non_combat_battleround_tick_monotonic
    assert first_due_at is not None

    fake_loop._now = float(first_due_at)
    battle_round_ticks.process_non_combat_battleround_tick(session)

    second_due_at = session.next_non_combat_battleround_tick_monotonic
    assert second_due_at is not None
    assert second_due_at == first_due_at + combat_state.COMBAT_ROUND_INTERVAL_SECONDS


def test_non_combat_battleround_scheduler_clears_when_no_activity(monkeypatch) -> None:
    session = _make_session("client-scheduler-clear", "Lucia")
    session.combat.skill_cooldowns["skill.bash"] = 1

    class _FakeLoop:
        def __init__(self, now: float):
            self._now = now

        def time(self) -> float:
            return self._now

    fake_loop = _FakeLoop(500.0)
    monkeypatch.setattr(battle_round_ticks.asyncio, "get_running_loop", lambda: fake_loop)

    battle_round_ticks.process_non_combat_battleround_tick(session)
    due_at = session.next_non_combat_battleround_tick_monotonic
    assert due_at is not None

    fake_loop._now = float(due_at)
    battle_round_ticks.process_non_combat_battleround_tick(session)

    assert session.next_non_combat_battleround_tick_monotonic is None


def test_out_of_combat_battle_round_affects_expire_on_elapsed_round_time(monkeypatch) -> None:
    session = _make_session("client-affect-expire", "Lucia")
    session.active_affects.append(ActiveAffectState(
        affect_id="affect.extra-hits",
        affect_name="Fist Flurry",
        affect_mode="battle_rounds",
        affect_type="extra_hits",
        extra_unarmed_hits=2,
        remaining_rounds=3,
    ))

    class _FakeLoop:
        def __init__(self, now: float):
            self._now = now

        def time(self) -> float:
            return self._now

    fake_loop = _FakeLoop(600.0)
    monkeypatch.setattr(battle_round_ticks.asyncio, "get_running_loop", lambda: fake_loop)

    battle_round_ticks.process_non_combat_battleround_tick(session)
    due_at = session.next_non_combat_battleround_tick_monotonic
    assert due_at is not None

    fake_loop._now = 600.0 + (combat_state.COMBAT_ROUND_INTERVAL_SECONDS * 3.0)
    battle_round_ticks.process_non_combat_battleround_tick(session)

    assert session.active_affects == []
    assert session.next_non_combat_battleround_tick_monotonic is None


def test_combat_and_non_combat_battleround_parity_includes_affects(monkeypatch) -> None:
    def _make_session_with_affect_activity(client_id: str) -> ClientSession:
        session = _make_session(client_id, "Parity Affect")
        session.active_affects.append(ActiveAffectState(
            affect_id="affect.extra-hits",
            affect_name="Fist Flurry",
            affect_mode="battle_rounds",
            affect_type="extra_hits",
            extra_unarmed_hits=2,
            remaining_rounds=4,
        ))
        return session

    class _FakeLoop:
        def __init__(self, now: float):
            self._now = now

        def time(self) -> float:
            return self._now

    fake_loop = _FakeLoop(700.0)
    monkeypatch.setattr(battle_round_ticks.asyncio, "get_running_loop", lambda: fake_loop)

    n_rounds = 2
    interval = combat_state.COMBAT_ROUND_INTERVAL_SECONDS

    session_nc = _make_session_with_affect_activity("client-affect-parity-nc")
    battle_round_ticks.process_non_combat_battleround_tick(session_nc)
    fake_loop._now = 700.0 + (interval * n_rounds)
    battle_round_ticks.process_non_combat_battleround_tick(session_nc)

    session_c = _make_session_with_affect_activity("client-affect-parity-c")
    for _ in range(n_rounds):
        _process_combat_round_timers(session_c, [])

    assert len(session_c.active_affects) == len(session_nc.active_affects)
    for combat_affect, noncombat_affect in zip(session_c.active_affects, session_nc.active_affects):
        assert combat_affect.remaining_rounds == noncombat_affect.remaining_rounds
