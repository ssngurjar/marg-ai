"""What a provider call cost (contracts §2.3). Attached to every turn_steps row.

Domain data, so provider ports can return it without importing the pipeline.
"""

from collections.abc import Iterable
from decimal import Decimal

from app.domain.models.base import DomainModel


class StepUsage(DomainModel):
    provider: str | None  # "meta_model_api", "llama_guard", "ml_sidecar", …
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    audio_seconds: Decimal | None
    cost_usd: Decimal  # Decimal("0") when free

    @classmethod
    def total(cls, usages: list["StepUsage"]) -> "StepUsage | None":
        """One turn_steps row for a step that made several calls: tokens and cost added up,
        providers and models joined in call order ("llama_guard+meta_model_api")."""
        if not usages:
            return None
        return cls(
            provider=_joined(usage.provider for usage in usages),
            model=_joined(usage.model for usage in usages),
            input_tokens=sum(usage.input_tokens or 0 for usage in usages),
            output_tokens=sum(usage.output_tokens or 0 for usage in usages),
            audio_seconds=None,
            cost_usd=sum((usage.cost_usd for usage in usages), start=Decimal(0)),
        )


def _joined(names: Iterable[str | None]) -> str | None:
    distinct = list(dict.fromkeys(name for name in names if name))
    return "+".join(distinct) or None
