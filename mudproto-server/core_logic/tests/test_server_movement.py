from server_movement import DIRECTION_OPPOSITES, _format_arrival_origin


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
