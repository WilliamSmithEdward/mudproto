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
    assert "Structured protocol renderer" not in content
    assert "Pure HTML + CSS + JavaScript" not in content
    assert "Local controls:" not in content
    assert "height: calc(100vh - 28px);" in content
    assert "overflow: hidden;" in content
    assert "scrollbar-gutter: stable;" in content
    assert "::-webkit-scrollbar" in content
    assert "scrollbar-color: #3a3a3a #070707;" in content
    assert "color: #61d6d6;" in content
    assert "requestAnimationFrame" in content
    assert "createDocumentFragment" in content
    assert "text-rendering: optimizeLegibility;" in content
    assert "/clear" in content
    assert "/quit" in content
