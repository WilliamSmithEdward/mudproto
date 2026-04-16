from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLIENT_DIFF_DOC = PROJECT_ROOT / "mudproto_client_web" / "documentation" / "client-differences.md"


def test_client_difference_documentation_exists_and_is_clear() -> None:
    assert CLIENT_DIFF_DOC.exists(), "Expected client difference documentation to exist."

    content = CLIENT_DIFF_DOC.read_text(encoding="utf-8")

    assert "Shared behavior that should stay aligned" in content
    assert "Current intentional differences" in content
    assert "Connection security" in content
    assert "Windowing and layout" in content
    assert "When a new difference is introduced between the clients, document it here in the same change." in content
