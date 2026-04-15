"""Shared outbound typing aliases for command handlers."""

from typing import Literal

OutboundMessage = dict[str, object]
OutboundResult = OutboundMessage | list[OutboundMessage]
ErrorContext = dict[str, object]
ErrorCode = Literal[
    "usage",
    "unknown-command",
    "target-not-found",
    "corpse-not-found",
    "no-merchant-here",
    "merchant-item-unavailable",
    "merchant-out-of-stock",
    "merchant-insufficient-coins",
    "merchant-not-carrying",
    "not-enough-vigor",
    "not-enough-mana",
    "not-engaged",
    "current-room-not-found",
    "cannot-go",
]
