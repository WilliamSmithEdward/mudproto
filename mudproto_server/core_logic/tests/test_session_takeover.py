import asyncio

import session_lifecycle
from models import ClientSession
from session_registry import active_character_sessions, connected_clients
from world import Room


class _FakeTask:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _FakeWebSocket:
    def __init__(self) -> None:
        self.closed_with: list[tuple[int | None, str | None]] = []

    async def close(self, code: int | None = None, reason: str | None = None) -> None:
        self.closed_with.append((code, reason))


def _make_session(client_id: str, name: str) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=_FakeWebSocket(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    return session


def test_complete_login_replaces_all_other_sessions_for_same_character(monkeypatch) -> None:
    old_active = _make_session("client-old-active", "Orlandu")
    old_active.scheduler_task = _FakeTask()
    old_active.status.hit_points = 52

    old_extra = _make_session("client-old-extra", "Orlandu")
    incoming = _make_session("client-new", "Orlandu")
    incoming.is_authenticated = False
    incoming.player_state_key = ""
    incoming.authenticated_character_name = ""

    previous_active = dict(active_character_sessions)
    previous_connected = dict(connected_clients)
    active_character_sessions.clear()
    connected_clients.clear()
    active_character_sessions["orlandu"] = old_active
    connected_clients[old_active.client_id] = old_active
    connected_clients[old_extra.client_id] = old_extra
    connected_clients[incoming.client_id] = incoming

    monkeypatch.setattr(session_lifecycle, "clear_transient_interaction_flags_for_session", lambda _session: 0)
    monkeypatch.setattr(session_lifecycle, "purge_nonpersistent_items", lambda _session, reason="": 0)
    monkeypatch.setattr(session_lifecycle, "save_player_state", lambda _session, player_key=None: None)
    monkeypatch.setattr(session_lifecycle, "maybe_auto_engage_current_room", lambda _session: None)
    monkeypatch.setattr(session_lifecycle, "get_room", lambda room_id: Room(room_id=room_id, title="Start", description="A start room."))
    monkeypatch.setattr(
        session_lifecycle,
        "display_room",
        lambda _session, _room: {"type": "display", "payload": {"lines": [[], [{"text": "Room line", "fg": "bright_white", "bold": False}]]}},
    )
    monkeypatch.setattr(session_lifecycle, "prepend_room_enter_communications", lambda result, _session, _room_id: result)

    scheduled_closes: list[asyncio.Future | object] = []

    def _run_immediately(coroutine):
        scheduled_closes.append(coroutine)
        asyncio.run(coroutine)
        return object()

    monkeypatch.setattr(session_lifecycle.asyncio, "create_task", _run_immediately)

    try:
        session_lifecycle.complete_login(
            incoming,
            {
                "character_key": "orlandu",
                "character_name": "Orlandu",
                "class_id": "class.monk",
                "gender": "male",
                "login_room_id": "start",
            },
            is_new_character=False,
        )

        assert incoming.is_authenticated is True
        assert active_character_sessions.get("orlandu") is incoming
        assert incoming.status.hit_points == 52

        assert old_active.disconnected_by_server is True
        assert old_active.is_connected is False
        assert old_active.is_authenticated is False
        assert old_active.player_state_key == ""
        assert old_active.scheduler_task.cancelled is True

        assert old_extra.disconnected_by_server is True
        assert old_extra.is_connected is False
        assert old_extra.is_authenticated is False
        assert old_extra.player_state_key == ""

        old_active_socket = old_active.websocket
        old_extra_socket = old_extra.websocket
        assert isinstance(old_active_socket, _FakeWebSocket)
        assert isinstance(old_extra_socket, _FakeWebSocket)
        assert old_active_socket.closed_with
        assert old_extra_socket.closed_with
        assert len(scheduled_closes) == 2
    finally:
        active_character_sessions.clear()
        active_character_sessions.update(previous_active)
        connected_clients.clear()
        connected_clients.update(previous_connected)
