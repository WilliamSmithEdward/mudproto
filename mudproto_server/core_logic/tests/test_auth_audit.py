import asyncio
import json
import sqlite3

import player_state_db
from commands import process_input_message
from models import ClientSession
from session_timing import is_session_lagged


class _FakeHeaders(dict):
    def items(self):
        return super().items()


class _FakeRequest:
    def __init__(self) -> None:
        self.path = "/"
        self.headers = _FakeHeaders({
            "User-Agent": "pytest",
            "X-Forwarded-For": "203.0.113.5",
        })


class _FakeWebSocket:
    def __init__(self) -> None:
        self.remote_address = ("203.0.113.5", 54321)
        self.local_address = ("127.0.0.1", 8765)
        self.request = _FakeRequest()
        self.closed_with: list[tuple[int | None, str | None]] = []

    async def close(self, code: int | None = None, reason: str | None = None) -> None:
        self.closed_with.append((code, reason))


def _make_session(client_id: str) -> ClientSession:
    from protocol import utc_now_iso

    return ClientSession(
        client_id=client_id,
        websocket=_FakeWebSocket(),  # type: ignore[arg-type]
        connected_at=utc_now_iso(),
    )


def _input_message(text: str) -> dict:
    return {
        "type": "input",
        "payload": {
            "text": text,
        },
    }


def _flatten_display_lines(outbound: dict | list[dict]) -> str:
    messages = outbound if isinstance(outbound, list) else [outbound]
    rendered: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        payload = message.get("payload", {})
        lines = payload.get("lines", []) if isinstance(payload, dict) else []
        for line in lines:
            if not isinstance(line, list):
                continue
            rendered.append("".join(str(part.get("text", "")) for part in line if isinstance(part, dict)))
    return "\n".join(rendered)


def test_login_attempts_and_results_are_logged_to_database(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "auth.sqlite3"
    monkeypatch.setattr(player_state_db, "PLAYER_STATE_DB_PATH", db_path)

    player_state_db.create_character(
        character_name="Orlandu",
        password="secret",
        class_id="class.monk",
        gender="male",
        login_room_id="start",
    )

    async def _run() -> None:
        session = _make_session("client-login-audit")

        first = await process_input_message(_input_message("Orlandu"), session)
        second = await process_input_message(_input_message("secret"), session)

        assert isinstance(first, dict)
        assert isinstance(second, dict | list)

    asyncio.run(_run())

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT event_type, success, character_name, failure_reason, remote_address, request_path, headers_json FROM login_audit ORDER BY id"
        ).fetchall()

    assert len(rows) >= 2
    assert any(str(row["event_type"]) == "character_lookup" and int(row["success"]) == 1 for row in rows)
    assert any(str(row["event_type"]) == "password_attempt" and int(row["success"]) == 1 for row in rows)
    assert any("203.0.113.5" in str(row["remote_address"]) for row in rows)
    assert any(str(row["request_path"]) == "/" for row in rows)
    assert any("User-Agent" in str(row["headers_json"]) for row in rows)


def test_failed_passwords_are_logged_lagged_and_disconnect_after_three_attempts(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "auth.sqlite3"
    monkeypatch.setattr(player_state_db, "PLAYER_STATE_DB_PATH", db_path)

    player_state_db.create_character(
        character_name="Orlandu",
        password="secret",
        class_id="class.monk",
        gender="male",
        login_room_id="start",
    )

    async def _run() -> None:
        session = _make_session("client-password-fail")

        await process_input_message(_input_message("Orlandu"), session)

        for attempt_index in range(2):
            outbound = await process_input_message(_input_message("wrongpass"), session)
            assert "Invalid password." in _flatten_display_lines(outbound)
            assert session.failed_password_attempts == attempt_index + 1
            assert is_session_lagged(session) is True
            assert session.disconnected_by_server is False
            session.lag_until_monotonic = asyncio.get_running_loop().time() - 0.01

        outbound = await process_input_message(_input_message("wrongpass"), session)

        assert "Too many failed password attempts" in _flatten_display_lines(outbound)
        assert session.failed_password_attempts == 3
        assert session.disconnected_by_server is True
        assert session.is_connected is False

    asyncio.run(_run())

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT event_type, success, failure_reason FROM login_audit WHERE event_type = 'password_attempt' ORDER BY id"
        ).fetchall()

    assert len(rows) == 3
    assert all(int(row["success"]) == 0 for row in rows)
    assert all(str(row["failure_reason"]) == "invalid_password" for row in rows)


def test_failed_password_lag_blocks_immediate_retry(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "auth.sqlite3"
    monkeypatch.setattr(player_state_db, "PLAYER_STATE_DB_PATH", db_path)

    player_state_db.create_character(
        character_name="Orlandu",
        password="secret",
        class_id="class.monk",
        gender="male",
        login_room_id="start",
    )

    async def _run() -> None:
        session = _make_session("client-password-lag")

        await process_input_message(_input_message("Orlandu"), session)
        first = await process_input_message(_input_message("wrongpass"), session)
        blocked = await process_input_message(_input_message("wrongpass"), session)

        assert "Invalid password." in _flatten_display_lines(first)
        assert "Please wait a moment before trying again." in _flatten_display_lines(blocked)
        assert session.failed_password_attempts == 1

    asyncio.run(_run())
