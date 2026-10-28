"""Shared type aliases with no domain meaning of their own."""

from typing import Literal

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
"""Any JSON value, spelled out so nothing needs `Any` (contracts §2.1)."""

type ReasoningEffort = Literal["minimal", "low", "medium", "high"]

# The ML sidecar's speech model (s06 §4.7): Kokoro-82M. Another model plugs in by adding its
# name here and in SidecarSynthesizer.MODELS, and an engine in services/ml_sidecar.
type TtsEngine = Literal["kokoro"]
"""How much hidden reasoning a model spends (s05 §4.1; `none` returns 400 on Muse Spark)."""
