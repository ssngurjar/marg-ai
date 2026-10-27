"""LayerResult: what every layer's generate step returns (s12 §4, s05 §4.4a).

Grows in stages: S10b adds `writes` (TurnWrites applied with the outbox), `fallback_reply` (the
reviewed text to send if the generated one is blocked) and `hazard_rule` (the hazards the d7 rule
allows on this reply; None when the rule doesn't apply).
"""

from typing import Literal

from pydantic import Field

from app.domain.enums import StepOutcome
from app.domain.models.base import DomainModel
from app.domain.models.reply import CanonicalReply
from app.domain.models.usage import StepUsage
from app.domain.models.writes import TurnWrite


class LayerResult(DomainModel):
    reply: CanonicalReply
    usages: list[StepUsage]  # summed into the one GENERATE step row
    prompt_versions: dict[str, str]  # prompt id → version, for every prompt the layer used
    outcome: Literal[StepOutcome.OK, StepOutcome.DEGRADED]
    degraded_reason: str | None  # fixed vocabulary, set when outcome is DEGRADED
    writes: list[TurnWrite] = Field(default_factory=list)
    fallback_reply: CanonicalReply | None = None  # reviewed text, if the generated reply is blocked
    hazard_rule: frozenset[str] | None = None  # declared hazards the d7 rule allows
