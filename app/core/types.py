"""Shared type aliases with no domain meaning of their own."""

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
"""Any JSON value, spelled out so nothing needs `Any` (contracts §2.1)."""
