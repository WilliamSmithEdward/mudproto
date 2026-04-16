from pathlib import Path


def _readme_text() -> str:
    readme_path = Path(__file__).resolve().parents[3] / "README.md"
    return readme_path.read_text(encoding="utf-8")


def test_readme_uses_stable_centered_markup() -> None:
    text = _readme_text()

    assert '<h1 align="center">MudProto</h1>' in text
    assert '<div align="center">' not in text
    assert "## Quick Start" in text
    assert text.index("## Quick Start") > text.index("<h1 align=\"center\">MudProto</h1>")


def test_readme_project_tree_and_code_fences_are_balanced() -> None:
    text = _readme_text()

    assert text.count("```") % 2 == 0
    assert "```text\nmudproto/\n├── ARCHITECTURE.md" in text
    assert "└── README.md" in text
