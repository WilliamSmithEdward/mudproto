import json
import re
from pathlib import Path

from display_core import resolve_display_color
from settings import DISPLAY_COLORS_FILE, DISPLAY_COLOR_MAP


_RAW_COLOR_NAMES = {
    "bright_white",
    "bright_cyan",
    "bright_yellow",
    "bright_green",
    "bright_red",
    "bright_black",
    "bright_magenta",
    "bright_blue",
    "orange",
}


def test_display_colors_json_no_longer_contains_legacy_alias_keys() -> None:
    with Path(DISPLAY_COLORS_FILE).open("r", encoding="utf-8") as handle:
        raw_map = json.load(handle)

    assert isinstance(raw_map, dict)
    assert not (_RAW_COLOR_NAMES & {str(key).strip() for key in raw_map})


def test_resolve_display_color_does_not_passthrough_unknown_keys() -> None:
    resolved_default = str(DISPLAY_COLOR_MAP["display_core.default_fg"]).strip()
    assert resolve_display_color("legacy.unmapped.color") == resolved_default


def test_production_code_uses_semantic_color_keys() -> None:
    core_logic_root = Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    color_pattern = re.compile(r'"(?:bright_white|bright_cyan|bright_yellow|bright_green|bright_red|bright_black|bright_magenta|bright_blue|orange)"')

    for path in core_logic_root.rglob("*.py"):
        if "tests" in path.parts:
            continue
        if path.name in {"display_core.py", "settings.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        if color_pattern.search(text):
            offenders.append(str(path.relative_to(core_logic_root.parent)).replace("\\", "/"))

    assert offenders == []
