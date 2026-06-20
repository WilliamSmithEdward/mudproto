"""Tests for websocket send behavior, including the send timeout (RG-23)."""

import asyncio

import server_transport


class _FastWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)


class _SlowWebSocket:
    async def send(self, _text: str) -> None:
        await asyncio.sleep(5)


def test_send_json_sends_within_timeout() -> None:
    websocket = _FastWebSocket()

    delivered = asyncio.run(server_transport.send_json(websocket, {"a": 1}))

    assert delivered is True
    assert websocket.sent and '"a": 1' in websocket.sent[0]


def test_send_json_returns_false_on_send_timeout(monkeypatch) -> None:
    monkeypatch.setattr(server_transport, "SEND_TIMEOUT_SECONDS", 0.01)

    delivered = asyncio.run(server_transport.send_json(_SlowWebSocket(), {"hello": "world"}))

    assert delivered is False
