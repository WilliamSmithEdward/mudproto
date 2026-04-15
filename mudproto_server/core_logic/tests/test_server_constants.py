from combat_state import get_health_condition
from display_feedback import _direction_short_label, _direction_sort_key
from settings import ATTRIBUTE_MAX_CAP, DIRECTION_ALIASES, DIRECTION_SHORT_LABELS, DIRECTION_SORT_ORDER, HEALTH_CONDITION_BANDS


def test_direction_maps_are_loaded_and_used_by_prompt_helpers() -> None:
    assert DIRECTION_SHORT_LABELS["north"] == "N"
    assert DIRECTION_SHORT_LABELS["down"] == "D"
    assert DIRECTION_ALIASES["n"] == "north"
    assert DIRECTION_ALIASES["w"] == "west"

    assert _direction_short_label("north") == "N"
    assert _direction_short_label("west") == "W"
    assert _direction_sort_key("north") == (DIRECTION_SORT_ORDER["north"], "north")
    assert _direction_sort_key("down") == (DIRECTION_SORT_ORDER["down"], "down")


def test_attribute_cap_is_loaded_from_server_settings() -> None:
    assert ATTRIBUTE_MAX_CAP == 28


def test_health_condition_thresholds_are_loaded_and_applied() -> None:
    assert len(HEALTH_CONDITION_BANDS) >= 4
    assert get_health_condition(15, 100) == ("awful", "bright_red")
    assert get_health_condition(30, 100) == ("very poor", "bright_red")
    assert get_health_condition(60, 100) == ("average", "bright_yellow")
    assert get_health_condition(90, 100) == ("good", "bright_green")
    assert get_health_condition(99, 100) == ("very good", "bright_green")
    assert get_health_condition(100, 100) == ("perfect", "bright_green")
