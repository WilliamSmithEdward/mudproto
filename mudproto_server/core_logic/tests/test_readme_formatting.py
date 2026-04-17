from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _readme_text() -> str:
    readme_path = _repo_root() / "README.md"
    return readme_path.read_text(encoding="utf-8")


def _markdown_files() -> list[Path]:
    return sorted(_repo_root().rglob("*.md"))


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


def test_markdown_files_have_no_mojibake_sequences() -> None:
    suspicious_sequences = (
        "â€”",
        "â†’",
        "â€™",
        "â€œ",
        "â€",
        "Ã—",
        "â”",
        "�",
    )

    offenders: list[str] = []
    for path in _markdown_files():
        text = path.read_text(encoding="utf-8")
        if any(sequence in text for sequence in suspicious_sequences):
            offenders.append(path.relative_to(_repo_root()).as_posix())

    assert offenders == []


def test_llm_instruction_files_reference_current_affect_model() -> None:
    repo_root = _repo_root()
    llm_doc = (repo_root / "LLM_CONTENT_GENERATION.md").read_text(encoding="utf-8")
    asset_doc = (repo_root / "ASSET_GENERATION.md").read_text(encoding="utf-8")
    instruction_json = (repo_root / "mudproto_llm_interfaces" / "asset_payload_generation_instructions.json").read_text(encoding="utf-8")
    combined = "\n".join([llm_doc, asset_doc, instruction_json])

    assert "affect.received-damage" in combined
    assert "affect.dealt-damage" in combined
    assert "affect.regeneration" in combined
    assert "affect.extra-hits" in combined
    assert "override objects with affect_id plus" in combined
    assert "equipment_effects" in combined
    assert "weapon_damage" in combined
    assert "hitroll" in combined
    assert "passive while-equipped bonuses" in combined
    assert "Only string references are supported" not in combined
    assert "affect.increase-received-damage" not in combined
