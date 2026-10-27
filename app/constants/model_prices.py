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
    # Llama Guard 4 12B at $0.20 / 1M in and out (Groq, 2026-10-27). Groq has since
    # decommissioned it; host and price await the owner (docs/reviews/owner-review-pending.md).
    "meta-llama/llama-guard-4-12b": ModelPrice(
        Decimal("0.20"), Decimal("0.20"), Decimal("0.20"), allowed_for_user_content=True
    ),
}
