import combat_state
import battle_round_ticks
from combat_state import _process_combat_round_timers, tick_out_of_combat_cooldowns
from models import ClientSession


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

    tick_out_of_combat_cooldowns(session)
    assert session.combat.skill_cooldowns["skill.bash"] == 3

    fake_loop._now = 100.0 + combat_state.COMBAT_ROUND_INTERVAL_SECONDS
    tick_out_of_combat_cooldowns(session)

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

    tick_out_of_combat_cooldowns(session)
    fake_loop._now = 200.0 + (combat_state.COMBAT_ROUND_INTERVAL_SECONDS * 3.0)
    tick_out_of_combat_cooldowns(session)

    assert "skill.bash" not in session.combat.skill_cooldowns


def test_in_combat_round_timers_tick_skill_cooldowns() -> None:
    session = _make_session("client-cooldown-in", "Lucia")
    session.combat.skill_cooldowns["skill.bash"] = 3

    _process_combat_round_timers(session, [])

    assert session.combat.skill_cooldowns["skill.bash"] == 2
