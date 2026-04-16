import asyncio
import logging
import sys

import server
import websockets

from server import _SuppressExpectedHandshakeNoise, _is_expected_handshake_disconnect, _validate_inbound_message_size


def _build_invalid_handshake_error() -> BaseException:
    try:
        try:
            raise EOFError("connection closed while reading HTTP request line")
        except EOFError as exc:
            raise websockets.exceptions.InvalidMessage("did not receive a valid HTTP request") from exc
    except websockets.exceptions.InvalidMessage as exc:
        return exc


def test_expected_handshake_disconnect_is_recognized() -> None:
    exc = _build_invalid_handshake_error()

    assert _is_expected_handshake_disconnect(exc) is True


def test_handshake_filter_removes_traceback_for_expected_disconnect() -> None:
    exc = _build_invalid_handshake_error()
    record = logging.LogRecord(
        name="mudproto.websocket",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="opening handshake failed",
        args=(),
        exc_info=(type(exc), exc, exc.__traceback__),
    )

    allowed = _SuppressExpectedHandshakeNoise().filter(record)

    assert allowed is True
    assert record.getMessage() == "WebSocket handshake closed before a valid request was received."
    assert record.exc_info is None


def test_handshake_filter_keeps_unexpected_errors_verbose() -> None:
    exc = ValueError("boom")
    try:
        raise exc
    except ValueError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="mudproto.websocket",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="opening handshake failed",
        args=(),
        exc_info=exc_info,
    )

    allowed = _SuppressExpectedHandshakeNoise().filter(record)

    assert allowed is True
    assert record.getMessage() == "opening handshake failed"
    assert record.exc_info == exc_info


class _FakeWebSocket:
    def __init__(self) -> None:
        self.closed_with: list[tuple[int | None, str | None]] = []

    async def close(self, code: int | None = None, reason: str | None = None) -> None:
        self.closed_with.append((code, reason))


def _flatten_display_text(message: dict) -> str:
    payload = message.get("payload", {})
    lines = payload.get("lines", []) if isinstance(payload, dict) else []
    rendered: list[str] = []
    for line in lines:
        if not isinstance(line, list):
            continue
        rendered.append("".join(str(part.get("text", "")) for part in line if isinstance(part, dict)))
    return "\n".join(rendered)


def test_validate_inbound_message_size_rejects_oversized_payload(monkeypatch) -> None:
    monkeypatch.setattr(server, "MAX_MESSAGE_SIZE_BYTES", 8)

    assert _validate_inbound_message_size("123456789") == "Message exceeds the 8-byte limit."
    assert _validate_inbound_message_size("12345678") is None


def test_handle_connection_rejects_when_server_is_full(monkeypatch) -> None:
    websocket = _FakeWebSocket()
    sent_messages: list[dict] = []

    async def _capture_send_json(_websocket, message: dict) -> bool:
        sent_messages.append(message)
        return True

    monkeypatch.setattr(server, "register_client", lambda _client_id, _websocket: None)
    monkeypatch.setattr(server, "send_json", _capture_send_json)

    asyncio.run(server.handle_connection(websocket))

    assert sent_messages
    assert "Server is full" in _flatten_display_text(sent_messages[0])
    assert websocket.closed_with == [(1013, "Server full")]
