"""What a provider call cost (contracts §2.3). Attached to every turn_steps row.

Domain data, so provider ports can return it without importing the pipeline.
"""

from decimal import Decimal

from app.domain.models.base import DomainModel


class StepUsage(DomainModel):
    provider: str | None  # "meta_model_api", "llama_guard", "ml_sidecar", …
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    audio_seconds: Decimal | None
    cost_usd: Decimal  # Decimal("0") when free
