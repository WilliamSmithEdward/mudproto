"""Accessibility regression checks for the web client (UI/UX guidelines).

Presence checks against index.html for the keyboard-focus, reduced-motion, and
modal focus-trap affordances. The suite does not run a browser, so these match
the existing web client tests' source-inspection style.
"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_CLIENT_INDEX = PROJECT_ROOT / "mudproto_client_web" / "index.html"


def _read_index() -> str:
    return WEB_CLIENT_INDEX.read_text(encoding="utf-8")


def test_buttons_have_visible_focus_indicator() -> None:
    assert ":focus-visible" in _read_index()


def test_respects_reduced_motion_preference() -> None:
    html = _read_index()
    assert "prefers-reduced-motion" in html
    assert 'matchMedia("(prefers-reduced-motion: reduce)")' in html


def test_modals_have_focus_trap() -> None:
    html = _read_index()
    assert "trapFocusWithinModal" in html
    assert "getOpenModal" in html
