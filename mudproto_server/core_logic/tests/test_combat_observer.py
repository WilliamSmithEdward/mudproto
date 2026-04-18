from combat_observer import _attach_room_broadcast_lines, _resolve_combat_context


def test_resolve_combat_context_preserves_exclamation() -> None:
    text = _resolve_combat_context("[a/an] [verb] viciously slammed to the ground!", target_text="you", verb="is")
    assert text.endswith("!")
    assert not text.endswith("!.")


def test_resolve_combat_context_preserves_question_mark() -> None:
    text = _resolve_combat_context("[a/an] [verb] staggered?", target_text="the target", verb="is")
    assert text.endswith("?")
    assert not text.endswith("?.")


def test_resolve_combat_context_adds_period_when_missing() -> None:
    text = _resolve_combat_context("[a/an] [verb] rattled", target_text="the target", verb="is")
    assert text.endswith(".")


def test_resolve_combat_context_normalizes_you_is_to_you_are() -> None:
    text = _resolve_combat_context("[a/an] [verb] knocked backward", target_text="you", verb="is")
    assert text.startswith("You are")


def test_resolve_combat_context_cinder_kiss_template_for_player_target() -> None:
    text = _resolve_combat_context(
        "[a/an] [verb] torn into by a hungry spear of cinders!",
        target_text="you",
        verb="are",
    )
    assert text == "You are torn into by a hungry spear of cinders!"


def test_attach_room_broadcast_lines_sets_broadcast_flag() -> None:
    outbound: dict = {"type": "display", "payload": {"lines": []}}
    _attach_room_broadcast_lines(outbound, ["Gandalf casts fireball."])
    assert outbound["payload"]["broadcast_to_room"] is True


def test_attach_room_broadcast_lines_sets_flag_even_with_empty_lines() -> None:
    outbound: dict = {"type": "display", "payload": {"lines": []}}
    _attach_room_broadcast_lines(outbound, [])
    assert outbound["payload"]["broadcast_to_room"] is True
