from server_movement import DIRECTION_OPPOSITES, _format_arrival_origin
import command_handlers.movement as movement
from models import ClientSession
from typing import Any, cast


def test_direction_opposites_contains_only_supported_directions() -> None:
    expected_keys = {"north", "south", "east", "west", "up", "down"}
    assert set(DIRECTION_OPPOSITES.keys()) == expected_keys


def test_direction_opposites_excludes_diagonals() -> None:
    for diagonal in {"northeast", "northwest", "southeast", "southwest"}:
        assert diagonal not in DIRECTION_OPPOSITES


def test_format_arrival_origin_cardinal_and_vertical() -> None:
    assert _format_arrival_origin("north") == "the north"
    assert _format_arrival_origin("south") == "the south"
    assert _format_arrival_origin("east") == "the east"
    assert _format_arrival_origin("west") == "the west"
    assert _format_arrival_origin("up") == "above"
    assert _format_arrival_origin("down") == "below"


def test_format_arrival_origin_fallbacks() -> None:
    assert _format_arrival_origin("portal") == "portal"
    assert _format_arrival_origin("") == "somewhere"


def test_direction_move_alone_suffix_recognized_prefixes() -> None:
    for suffix in ["al", "alo", "alon", "alone"]:
        assert movement._direction_move_is_alone([suffix]) is True


def test_direction_move_alone_suffix_not_set_without_alias() -> None:
    assert movement._direction_move_is_alone([]) is False
    assert movement._direction_move_is_alone(["group"]) is False


def test_handle_movement_command_sets_allow_followers_false_for_alone_suffix(monkeypatch) -> None:
    def fake_try_move(_session, _direction) -> dict[str, Any]:
        return {
            "type": "display",
            "payload": {
                "movement": {
                    "from_room_id": "room-a",
                    "to_room_id": "room-b",
                    "direction": "north",
                    "action": "leaves",
                    "allow_followers": True,
                },
            },
        }

    monkeypatch.setattr(movement, "try_move", fake_try_move)

    outbound = movement.handle_movement_command(cast(ClientSession, object()), "north", ["al"], "north al")
    assert isinstance(outbound, dict)
    outbound_payload = cast(dict[str, Any], outbound["payload"])
    movement_payload = cast(dict[str, Any], outbound_payload["movement"])
    assert movement_payload["allow_followers"] is False


def test_handle_movement_command_no_aliases_support_alone_suffix(monkeypatch) -> None:
    def fake_try_move(_session, _direction) -> dict[str, Any]:
        return {
            "type": "display",
            "payload": {
                "movement": {
                    "from_room_id": "room-a",
                    "to_room_id": "room-b",
                    "direction": "north",
                    "action": "leaves",
                    "allow_followers": True,
                },
            },
        }

    monkeypatch.setattr(movement, "try_move", fake_try_move)

    for verb, suffix in [("no", "al"), ("nor", "al"), ("nor", "alo")]:
        outbound = movement.handle_movement_command(cast(ClientSession, object()), verb, [suffix], f"{verb} {suffix}")
        assert isinstance(outbound, dict)
        outbound_payload = cast(dict[str, Any], outbound["payload"])
        movement_payload = cast(dict[str, Any], outbound_payload["movement"])
        assert movement_payload["allow_followers"] is False
