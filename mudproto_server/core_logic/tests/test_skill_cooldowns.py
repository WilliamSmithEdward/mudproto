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


def test_out_of_combat_skill_cooldowns_do_not_tick() -> None:
    session = _make_session("client-cooldown-out", "Lucia")
    session.combat.skill_cooldowns["skill.bash"] = 3

    tick_out_of_combat_cooldowns(session)

    assert session.combat.skill_cooldowns["skill.bash"] == 3


def test_in_combat_round_timers_tick_skill_cooldowns() -> None:
    session = _make_session("client-cooldown-in", "Lucia")
    session.combat.skill_cooldowns["skill.bash"] = 3

    _process_combat_round_timers(session, [])

    assert session.combat.skill_cooldowns["skill.bash"] == 2
