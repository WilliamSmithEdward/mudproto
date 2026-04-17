from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_CLIENT_DIRECTION_DOC = PROJECT_ROOT / "mudproto_client_web" / "documentation" / "web-client-direction.md"


def test_client_direction_documentation_exists_and_is_clear() -> None:
    assert WEB_CLIENT_DIRECTION_DOC.exists(), "Expected web client direction documentation to exist."

    content = WEB_CLIENT_DIRECTION_DOC.read_text(encoding="utf-8")

    assert "MudProto web-first client direction" in content
    assert "single supported player client" in content
    assert "avoid maintaining two different clients" in content
    assert "New player-facing UX work should land in the web client." in content
    assert "When client-facing behavior changes, update the web client docs and tests in the same change." in content
