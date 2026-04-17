from pathlib import Path
import re

import mudproto_client_gui.client_gui as client_gui


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_CLIENT_INDEX = PROJECT_ROOT / "mudproto_client_web" / "index.html"
GUI_CLIENT_SOURCE = (PROJECT_ROOT / "mudproto_client_gui" / "client_gui.py").read_text(encoding="utf-8")


def _read_web_source() -> str:
    return WEB_CLIENT_INDEX.read_text(encoding="utf-8")


def _extract_js_string_constant(content: str, name: str) -> str:
    match = re.search(rf'const\s+{re.escape(name)}\s*=\s*"([^"]+)";', content)
    assert match is not None, f"Expected {name} string constant in web client."
    return match.group(1)


def _extract_js_int_constant(content: str, name: str) -> int:
    match = re.search(rf"const\s+{re.escape(name)}\s*=\s*(\d+);", content)
    assert match is not None, f"Expected {name} integer constant in web client."
    return int(match.group(1))


def _extract_js_color_map(content: str) -> dict[str, str]:
    match = re.search(r"const COLOR_MAP = \{(.*?)\n    \};", content, re.DOTALL)
    assert match is not None, "Expected COLOR_MAP in web client."

    color_map: dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip().rstrip(",")
        if not line:
            continue
        key, value = line.split(":", 1)
        color_map[key.strip()] = value.strip().strip('"')
    return color_map


def test_web_client_default_server_uri_matches_gui_client() -> None:
    content = _read_web_source()

    assert _extract_js_string_constant(content, "DEFAULT_SERVER_URI") == client_gui.default_server_uri()


def test_web_client_reconnect_interval_matches_gui_client() -> None:
    content = _read_web_source()

    assert _extract_js_int_constant(content, "RECONNECT_INTERVAL_MS") == client_gui.RECONNECT_INTERVAL_MS


def test_web_client_color_map_matches_gui_client() -> None:
    content = _read_web_source()

    assert _extract_js_color_map(content) == client_gui.COLOR_MAP


def test_gui_and_web_clients_share_local_command_contract() -> None:
    content = _read_web_source()

    assert "#clear" in content
    assert "#quit" in content
    assert "ArrowUp" in content
    assert "ArrowDown" in content

    assert 'localCommand === "#clear"' in content
    assert 'localCommand === "#quit"' in content
    assert 'localCommand.startsWith("#")' in content
    assert '"#clear"' in GUI_CLIENT_SOURCE
    assert '"#quit"' in GUI_CLIENT_SOURCE
    assert 'startswith("#")' in GUI_CLIENT_SOURCE
    assert "def on_history_up" in GUI_CLIENT_SOURCE
    assert "def on_history_down" in GUI_CLIENT_SOURCE
    assert "clear_output" in GUI_CLIENT_SOURCE
    assert "on_close" in GUI_CLIENT_SOURCE


def test_gui_and_web_clients_share_settings_actions() -> None:
    content = _read_web_source()

    assert "Save Config" in content
    assert "Save Config As..." in content
    assert "Load Config" in content
    assert "Focus Input" not in content

    assert "def save_config" in GUI_CLIENT_SOURCE
    assert "def save_config_as" in GUI_CLIENT_SOURCE
    assert "def load_config_from_dialog" in GUI_CLIENT_SOURCE
    assert "def prompt_server_uri" in GUI_CLIENT_SOURCE
    assert 'label="Focus Input"' not in GUI_CLIENT_SOURCE
