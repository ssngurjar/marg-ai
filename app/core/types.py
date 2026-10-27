"""Shared type aliases with no domain meaning of their own."""

from typing import Literal

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
"""Any JSON value, spelled out so nothing needs `Any` (contracts §2.1)."""

type ReasoningEffort = Literal["minimal", "low", "medium", "high"]
"""How much hidden reasoning a model spends (s05 §4.1; `none` returns 400 on Muse Spark)."""
