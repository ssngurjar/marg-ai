"""LayerResult: what every layer's generate step returns (s12 §4, s05 §4.4a).

Grows in stages: S8 adds `writes` (TurnWrites applied with the outbox), with the first layer that
produces one.
"""

from typing import Literal

from app.domain.enums import StepOutcome
from app.domain.models.base import DomainModel
from app.domain.models.reply import CanonicalReply
from app.domain.models.usage import StepUsage


class LayerResult(DomainModel):
    reply: CanonicalReply
    usages: list[StepUsage]  # summed into the one GENERATE step row
    prompt_versions: dict[str, str]  # prompt id → version, for every prompt the layer used
    outcome: Literal[StepOutcome.OK, StepOutcome.DEGRADED]
    degraded_reason: str | None  # fixed vocabulary, set when outcome is DEGRADED
