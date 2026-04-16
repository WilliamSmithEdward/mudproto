import logging
import sys

import websockets

from server import _SuppressExpectedHandshakeNoise, _is_expected_handshake_disconnect


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
