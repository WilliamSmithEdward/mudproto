import assets


def _room_by_id(room_id: str) -> dict:
    for room in assets.load_rooms():
        if str(room.get("room_id", "")).strip() == room_id:
            return room
    raise AssertionError(f"Room '{room_id}' was not found.")


def _start_room_has_debug_helpers() -> tuple[bool, bool, bool, bool]:
    start_room = _room_by_id("start")
    keyword_actions = start_room.get("keyword_actions", [])
    room_objects = start_room.get("room_objects", [])

    has_circle_action = any(
        isinstance(action, dict)
        and "stand circle" in action.get("keywords", [])
        for action in keyword_actions
    )
    has_button_action = any(
        isinstance(action, dict)
        and "press easy button" in action.get("keywords", [])
        for action in keyword_actions
    )
    has_circle_object = any(
        isinstance(obj, dict)
        and str(obj.get("object_id", "")).strip() == "magic-circle"
        for obj in room_objects
    )
    has_button_object = any(
        isinstance(obj, dict)
        and str(obj.get("object_id", "")).strip() == "easy-button"
        for obj in room_objects
    )

    return has_circle_action, has_button_action, has_circle_object, has_button_object


def test_debug_helpers_hidden_when_debug_mode_disabled(monkeypatch) -> None:
    monkeypatch.setattr(assets, "DEBUG_MODE", False)
    assets.load_rooms.cache_clear()

    has_circle_action, has_button_action, has_circle_object, has_button_object = _start_room_has_debug_helpers()

    assert not has_circle_action
    assert not has_button_action
    assert not has_circle_object
    assert not has_button_object


def test_debug_helpers_visible_when_debug_mode_enabled(monkeypatch) -> None:
    monkeypatch.setattr(assets, "DEBUG_MODE", True)
    assets.load_rooms.cache_clear()

    has_circle_action, has_button_action, has_circle_object, has_button_object = _start_room_has_debug_helpers()

    assert has_circle_action
    assert has_button_action
    assert has_circle_object
    assert has_button_object
