"""Model prices per million tokens, for cost accounting (s05 §4.1, s07 §4.3).

Meta Model API prices are from plan.md §0. Contributor variants are listed only so startup can
refuse them for user content (CLAUDE.md §10): Meta may train on what they're sent.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Final


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_per_million: Decimal
    cached_input_per_million: Decimal
    output_per_million: Decimal
    allowed_for_user_content: bool


MODEL_PRICES: Final[dict[str, ModelPrice]] = {
    "muse-spark-1.3": ModelPrice(
        Decimal("1.25"), Decimal("0.15"), Decimal("4.25"), allowed_for_user_content=True
    ),
    "muse-spark-1.2": ModelPrice(
        Decimal("1.25"), Decimal("0.15"), Decimal("4.25"), allowed_for_user_content=True
    ),
    "muse-spark-1.1": ModelPrice(
        Decimal("1.25"), Decimal("0.15"), Decimal("4.25"), allowed_for_user_content=True
    ),
    "muse-spark-1.3-contributor": ModelPrice(
        Decimal("0.10"), Decimal("0.002"), Decimal("0.20"), allowed_for_user_content=False
    ),
    "muse-spark-1.2-contributor": ModelPrice(
        Decimal("0.10"), Decimal("0.002"), Decimal("0.20"), allowed_for_user_content=False
    ),
    # Muse Spark Open on Baseten (C9): $1.25 in, $0.15 cached in, $4.25 out per 1M tokens
    # (baseten.co/library/muse-spark-open, 2026-10-27). Spike E called the versioned id.
    "meta-models/muse-spark-open": ModelPrice(
        Decimal("1.25"), Decimal("0.15"), Decimal("4.25"), allowed_for_user_content=True
    ),
    "meta-models/muse-spark-open-1026": ModelPrice(
        Decimal("1.25"), Decimal("0.15"), Decimal("4.25"), allowed_for_user_content=True
    ),
    # Llama Guard 4 12B on DeepInfra: $0.18 / 1M tokens in and out, standard tier (listed on
    # deepinfra.com/meta-llama/Llama-Guard-4-12B, 2026-10-27). Groq retired it on 2026-03-05.
    "meta-llama/Llama-Guard-4-12B": ModelPrice(
        Decimal("0.18"), Decimal("0.18"), Decimal("0.18"), allowed_for_user_content=True
    ),
}

# Muse Voice Transcribe: $0.18 per hour of audio, billed in whole seconds (plan.md §0, s06 §4.5).
STT_PRICE_PER_HOUR: Final[dict[str, Decimal]] = {"muse-voice-transcribe-1.0": Decimal("0.18")}
