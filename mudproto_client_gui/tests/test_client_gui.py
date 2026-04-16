import asyncio
import json
import ssl
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


def test_render_display_long_line_then_prompt_has_single_boundary_newline() -> None:
    client = _make_client("")
    fake_output = _FakeTextWidget("> ")
    client.output_text = fake_output  # type: ignore[assignment]
    client.base_font = ("Consolas", 11)
    client.bold_font = ("Consolas", 11, "bold")
    client.output_ends_with_newline = False

    long_text = "A plain stone chamber used for early server testing. " * 3
    client.render_display_message({
        "type": "display",
        "payload": {
            "lines": [[{"text": long_text, "fg": "bright_white", "bold": False}]],
            "prompt_lines": [[{"text": "526H 311V 1531C 0X> ", "fg": "bright_white", "bold": False}]],
        },
    })

    assert fake_output.content == f"> \n{long_text}\n526H 311V 1531C 0X> "


def test_load_network_settings_prefers_client_gui_config(tmp_path, monkeypatch) -> None:
    gui_settings = tmp_path / "server_info.json"
    gui_settings.write_text(
        json.dumps({
            "network": {
                "host": "172.233.152.179",
                "port": 8765,
                "tls_enabled": True,
                "tls_verify_server": False,
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(client_gui, "CLIENT_GUI_SETTINGS_FILE", gui_settings)
    monkeypatch.setattr(client_gui, "SERVER_SETTINGS_FILE", tmp_path / "missing-server-settings.json")

    assert client_gui._load_network_settings()["host"] == "172.233.152.179"


def test_default_server_uri_switches_to_wss_when_tls_enabled(monkeypatch) -> None:
    monkeypatch.setattr(client_gui, "_load_network_settings", lambda: {
        "host": "example.com",
        "port": 9443,
        "tls_enabled": True,
    })

    assert client_gui.default_server_uri() == "wss://example.com:9443"


def test_build_client_ssl_context_for_wss_can_disable_verification(monkeypatch) -> None:
    monkeypatch.setattr(client_gui, "_load_network_settings", lambda: {
        "tls_enabled": True,
        "tls_verify_server": False,
    })

    context = client_gui.build_client_ssl_context("wss://example.com:9443")

    assert context is not None
    assert context.verify_mode == ssl.CERT_NONE
    assert context.check_hostname is False


def test_resolve_network_path_uses_server_root_for_configuration_paths() -> None:
    resolved = client_gui._resolve_network_path("configuration/server/encryption/server-ca.pem")

    assert resolved.as_posix().endswith("mudproto_server/configuration/server/encryption/server-ca.pem")
