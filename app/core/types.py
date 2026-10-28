"""Shared type aliases with no domain meaning of their own."""

from typing import Literal

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
"""Any JSON value, spelled out so nothing needs `Any` (contracts §2.1)."""

type ReasoningEffort = Literal["minimal", "low", "medium", "high"]

# The voice server's model (s06 §4.7, C8): kokoro for the submission, mms for local testing,
# indic_parler on a GPU.
type TtsEngine = Literal["mms", "indic_parler", "kokoro"]
"""How much hidden reasoning a model spends (s05 §4.1; `none` returns 400 on Muse Spark)."""
