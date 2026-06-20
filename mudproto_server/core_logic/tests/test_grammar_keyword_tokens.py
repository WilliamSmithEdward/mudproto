"""Tests for the shared keyword tokenizer helpers (UM-06)."""

from grammar import keyword_token_list, keyword_tokens


def test_keyword_tokens_lowercases_and_dedupes() -> None:
    assert keyword_tokens("Rusty Iron SWORD") == {"rusty", "iron", "sword"}
    assert keyword_tokens("sword sword") == {"sword"}


def test_keyword_tokens_splits_on_non_alphanumerics() -> None:
    assert keyword_tokens("2.training-sword!") == {"2", "training", "sword"}


def test_keyword_tokens_handles_non_strings_and_empty() -> None:
    assert keyword_tokens("") == set()
    assert keyword_tokens(123) == {"123"}


def test_keyword_token_list_preserves_order_and_duplicates() -> None:
    assert keyword_token_list("Big Bad Big") == ["big", "bad", "big"]
    assert keyword_token_list("") == []
