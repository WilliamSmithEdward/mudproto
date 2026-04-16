from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_CLIENT_INDEX = PROJECT_ROOT / "mudproto_client_web" / "index.html"


def test_web_client_index_contains_mudproto_websocket_ui() -> None:
    assert WEB_CLIENT_INDEX.exists(), "Expected mudproto_client_web/index.html to exist."

    content = WEB_CLIENT_INDEX.read_text(encoding="utf-8")

    assert "MudProto Web Client" in content
    assert "new WebSocket" in content
    assert "function buildInputMessage" in content
    assert "function renderDisplayMessage" in content
    assert "/clear" in content
    assert "/quit" in content
