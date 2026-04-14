import asyncio
from typing import Any, cast

import mudproto_client_gui.client_gui as client_gui


class _FakeEntry:
    def __init__(self, text: str) -> None:
        self.text = text

    def get(self) -> str:
        return self.text

    def delete(self, _start, _end=None) -> None:
        self.text = ""

    def insert(self, _index, value: str) -> None:
        self.text = value

    def icursor(self, _index) -> None:
        return None


class _FakeRoot:
    def after(self, _delay, callback, *args):
        callback(*args)
        return None


class _ImmediateFuture:
    def __init__(self, coroutine):
        self._coroutine = coroutine

    def result(self):
        return asyncio.run(self._coroutine)


class _ImmediateThread:
    def __init__(self, *, target=None, daemon=None):
        self._target = target
        self._daemon = daemon

    def start(self) -> None:
        if self._target is not None:
            self._target()


class _FakeTextWidget:
    def __init__(self, content: str = "") -> None:
        self.content = content
        self._tags: set[str] = set()

    def configure(self, **_kwargs) -> None:
        return None

    def insert(self, _index, text: str, _tag=None) -> None:
        self.content += text

    def see(self, _index) -> None:
        return None

    def tag_names(self):
        return tuple(self._tags)

    def tag_configure(self, tag_name: str, **_kwargs) -> None:
        self._tags.add(tag_name)

    def __str__(self) -> str:
        return "fake-output"


def _make_client(raw_text: str) -> client_gui.MudProtoGuiClient:
    raw_client = client_gui.MudProtoGuiClient.__new__(client_gui.MudProtoGuiClient)
    client = cast(Any, raw_client)
    client.input_entry = _FakeEntry(raw_text)
    client.command_history = []
    client.history_index = None
    client.history_stash = ""
    client.network_loop = object()
    client.root = _FakeRoot()
    client._closing = False
    return cast(client_gui.MudProtoGuiClient, client)


def test_on_submit_sends_blank_spaces_to_server(monkeypatch) -> None:
    client = _make_client("   ")
    sent: list[str] = []

    async def _fake_send(text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(client, "_send_text_async", _fake_send)
    monkeypatch.setattr(client_gui.asyncio, "run_coroutine_threadsafe", lambda coroutine, _loop: _ImmediateFuture(coroutine))
    monkeypatch.setattr(client_gui.threading, "Thread", _ImmediateThread)

    result = client.on_submit()

    assert result == "break"
    assert sent == ["   "]
    assert client.command_history == []


def test_on_submit_handles_clear_locally(monkeypatch) -> None:
    client = _make_client("  /clear  ")
    sent: list[str] = []
    cleared: list[bool] = []

    async def _fake_send(text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(client, "_send_text_async", _fake_send)
    monkeypatch.setattr(client_gui.asyncio, "run_coroutine_threadsafe", lambda coroutine, _loop: _ImmediateFuture(coroutine))
    monkeypatch.setattr(client_gui.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(client, "clear_output", lambda: cleared.append(True))

    result = client.on_submit()

    assert result == "break"
    assert cleared == [True]
    assert sent == []
    assert client.command_history == ["/clear"]


def test_on_submit_handles_quit_locally(monkeypatch) -> None:
    client = _make_client(" /quit ")
    sent: list[str] = []
    closed: list[bool] = []

    async def _fake_send(text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(client, "_send_text_async", _fake_send)
    monkeypatch.setattr(client_gui.asyncio, "run_coroutine_threadsafe", lambda coroutine, _loop: _ImmediateFuture(coroutine))
    monkeypatch.setattr(client_gui.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(client, "on_close", lambda: closed.append(True))

    result = client.on_submit()

    assert result == "break"
    assert closed == [True]
    assert sent == []
    assert client.command_history == ["/quit"]


def test_on_submit_keeps_raw_text_but_normalizes_history(monkeypatch) -> None:
    client = _make_client("  say hello  ")
    sent: list[str] = []

    async def _fake_send(text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(client, "_send_text_async", _fake_send)
    monkeypatch.setattr(client_gui.asyncio, "run_coroutine_threadsafe", lambda coroutine, _loop: _ImmediateFuture(coroutine))
    monkeypatch.setattr(client_gui.threading, "Thread", _ImmediateThread)

    result = client.on_submit()

    assert result == "break"
    assert sent == ["  say hello  "]
    assert client.command_history == ["say hello"]


def test_render_display_passes_lines_and_prompt_groups() -> None:
    client = _make_client("")
    appended: list[list[list[dict]]] = []

    client._append_line_group = lambda lines: appended.append(lines)  # type: ignore[method-assign]

    client.render_display_message({
        "type": "display",
        "payload": {
            "lines": [[], [{"text": "Adventurer's Ledger", "fg": "bright_white", "bold": True}]],
            "prompt_lines": [[{"text": "prompt", "fg": "bright_white", "bold": False}]],
        },
    })

    assert len(appended) == 1
    assert appended[0][0] == []
    assert appended[0][1][0]["text"] == "Adventurer's Ledger"
    assert appended[0][2][0]["text"] == "prompt"


def test_append_line_group_preserves_leading_blank_after_prompt_line() -> None:
    client = _make_client("")
    fake_output = _FakeTextWidget(">")
    client.output_text = fake_output  # type: ignore[assignment]
    client.base_font = ("Consolas", 11)
    client.bold_font = ("Consolas", 11, "bold")
    client.output_ends_with_newline = False

    client._append_line_group([
        [],
        [{"text": "Character found. Enter your password.", "fg": "bright_white", "bold": False}],
    ])

    assert fake_output.content == ">\n\nCharacter found. Enter your password."
