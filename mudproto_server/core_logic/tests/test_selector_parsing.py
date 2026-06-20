"""Characterization + unit tests for item/trade selector parsing (UM-06).

The item and trade parsers share structure but differ deliberately: the item
parser splits on whitespace and dots, while the trade parser splits on dots only
(so a space stays inside one token), and their error messages differ. These tests
pin both behaviors before and after consolidation.
"""

from commerce import _parse_trade_selector
from inventory import parse_item_selector


def test_parse_item_selector_splits_on_whitespace_and_dots() -> None:
    assert parse_item_selector("training sword") == (None, ["training", "sword"], None)
    assert parse_item_selector("2.training.sword") == (2, ["training", "sword"], None)
    assert parse_item_selector("2 training sword") == (2, ["training", "sword"], None)


def test_parse_item_selector_errors() -> None:
    assert parse_item_selector("") == (None, [], "Provide equipment keywords, e.g. training sword")
    assert parse_item_selector("0.sword") == (None, [], "Selector index must be 1 or greater.")
    assert parse_item_selector("3") == (None, [], "Provide at least one equipment keyword after the index.")


def test_parse_trade_selector_splits_on_dots_only() -> None:
    assert _parse_trade_selector("training sword") == (None, ["training sword"], None)
    assert _parse_trade_selector("2.sword") == (2, ["sword"], None)


def test_parse_trade_selector_errors() -> None:
    assert _parse_trade_selector("") == (None, [], "Provide an item selector.")
    assert _parse_trade_selector("0.sword") == (None, [], "Selector index must be 1 or greater.")
    assert _parse_trade_selector("3") == (None, [], "Provide at least one selector keyword after the index.")
