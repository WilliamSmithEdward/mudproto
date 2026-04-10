"""Shared outbound typing aliases for command handlers."""

OutboundMessage = dict[str, object]
OutboundResult = OutboundMessage | list[OutboundMessage]
