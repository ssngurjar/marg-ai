"""What a turn and its steps produce, and the two hooks steps report through (contracts §2.3, §3).

`StepRecorder` and `TurnObserver` live here rather than in providers/ports.py: their arguments
are these models, and ports may not import the pipeline (s04 decisions log, 2026-10-27).
`TurnOutcome` grows in stages: S8 adds `writes`, S13 and S12 add `post_turn`.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from app.domain.enums import (
    FailureKind,
    FixedReplyKind,
    Language,
    Route,
    SafetyDecision,
    StepName,
    StepOutcome,
)
from app.domain.models import TurnId
from app.pipeline.parts import ReplyDelivery


class StepModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)


class StepFailure(StepModel):
    step: StepName
    kind: FailureKind
    detail: str  # fixed vocabulary only: no user text, no phone numbers
    retryable: bool


class StepSuccess[OutputT](StepModel):
    step: StepName
    output: OutputT
    outcome: Literal[StepOutcome.OK, StepOutcome.DEGRADED]


class StepUsage(StepModel):
    """Attached to every turn_steps row."""

    provider: str | None  # "meta_model_api", "llama_guard", "ml_sidecar", …
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    audio_seconds: Decimal | None
    cost_usd: Decimal  # Decimal("0") when free


class TurnOutcome(StepModel):
    """What `run_turn` returns to the worker, which persists it in one transaction (s04 §4.7)."""

    turn_id: TurnId
    route: Route
    delivery: ReplyDelivery  # sealed: built only from a SafeReply
    fixed_reply_kind: FixedReplyKind | None
    user_text: str | None  # the combined text; the worker stores NULL for a CRISIS turn
    reply_text: str
    reply_register: Language
    prompt_versions: dict[str, str]  # prompt id → version, for every prompt used
    first_failure: StepFailure | None


class StepRecorder(Protocol):
    """Records each step as it finishes (the worker's implementation writes turn_steps)."""

    async def record(  # noqa: PLR0913  # contracts §3 fixes this keyword-only signature
        self,
        *,
        turn_id: TurnId,
        step: StepName,
        outcome: StepOutcome,
        started_at: datetime,
        duration_ms: int,
        usage: StepUsage | None,
        failure: StepFailure | None,
        detail: str | None,
        decision: SafetyDecision | None = None,
    ) -> None: ...

    async def set_turn_text(self, turn_id: TurnId, user_text: str) -> None: ...

    async def set_turn_route(self, turn_id: TurnId, route: Route) -> None: ...


class TurnObserver(Protocol):
    """Sees every step's result. Evals capture them (s15); production uses NullTurnObserver."""

    async def on_step(
        self,
        turn_id: TurnId,
        step: StepName,
        result: StepSuccess[object] | StepFailure,
        usage: StepUsage | None,
        duration_ms: int,
    ) -> None: ...
