"""What a turn and its steps produce (contracts §2.3). Data only.

`TurnOutcome` grows in stages: S8 added `writes`; S13 and S12 add `post_turn`.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import FailureKind, FixedReplyKind, Language, Route, StepName, StepOutcome
from app.domain.models.base import TurnId
from app.domain.models.curiosity import PostTurnTask
from app.domain.models.writes import TurnWrite
from app.pipeline.reply_parts_builder import ReplyDelivery


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
    writes: list[TurnWrite]  # applied in the finalize transaction, in this order (s08)
    post_turn: list[PostTurnTask] = Field(default_factory=list)  # after delivery (s13)
