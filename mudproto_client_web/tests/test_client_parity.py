from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_CLIENT_INDEX = PROJECT_ROOT / "mudproto_client_web" / "index.html"
README = PROJECT_ROOT / "README.md"
ARCHITECTURE = PROJECT_ROOT / "ARCHITECTURE.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_readme_advocates_web_first_direction() -> None:
    content = _read(README)

    assert "Web-first direction" in content
    assert "avoid maintaining two different clients" in content
    assert "mudproto_client_gui/" not in content


def test_architecture_reflects_supported_web_client() -> None:
    content = _read(ARCHITECTURE)

    assert "browser-based web client" in content
    assert "mudproto_client_web/index.html" in content
    assert "mudproto_client_gui/" not in content


def test_web_client_keeps_primary_settings_actions() -> None:
    content = _read(WEB_CLIENT_INDEX)

    assert "Save Config" in content
    assert "Save Config As..." in content
    assert "Load Config" in content
    assert "Load New Config" in content
    assert "Aliases" in content
    assert "Key Bindings" in content
    assert 'id="helpBtn"' in content
    assert 'id="helpBackBtn"' in content
    assert "Open Aliases Help" in content
    assert "Open Binds Help" in content
    assert "Open Actions Help" in content
    assert "Actions" in content
    assert "Focus Input" not in content
