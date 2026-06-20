"""Regression tests for combat proc/observer message color resolution.

combat._queue_private_combat_message and combat._record_observer_broadcast_line
call resolve_display_color. That name was previously missing from combat.py's
module-level imports, so weapon-proc messages and observer broadcast lines raised
NameError at runtime, a path the rest of the suite does not deterministically
exercise. These tests call both helpers directly to keep the import in place.
"""

from types import SimpleNamespace

import combat


def test_queue_private_combat_message_appends_styled_line() -> None:
    session = SimpleNamespace(pending_private_lines=[])

    combat._queue_private_combat_message(session, "Your blade flares with cold fire.")

    assert len(session.pending_private_lines) == 1
    part = session.pending_private_lines[0][0]
    assert part["text"] == "Your blade flares with cold fire."
    assert part["bold"] is True
    assert isinstance(part["fg"], str) and part["fg"]


def test_record_observer_broadcast_line_appends_styled_line() -> None:
    lines: list = []

    combat._record_observer_broadcast_line(lines, "The blade flares with cold fire.")

    assert len(lines) == 1
    part = lines[0][0]
    assert part["text"] == "The blade flares with cold fire."
    assert isinstance(part["fg"], str) and part["fg"]


def test_blank_messages_are_ignored() -> None:
    session = SimpleNamespace(pending_private_lines=[])
    lines: list = []

    combat._queue_private_combat_message(session, "   ")
    combat._record_observer_broadcast_line(lines, "")

    assert session.pending_private_lines == []
    assert lines == []
