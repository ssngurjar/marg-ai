"""Scorecard: one `marg eval` run, as committed to `evals/results/` (s15 §4.6).

The cases are synthetic, so a failed case's reply text can be kept for review; a passed case
keeps only its numbers, so scorecards stay short.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

CaseStatus = Literal["passed", "failed", "judge_error", "skipped"]
RUBRIC_NAMES = ("grounding", "cultural_resonance", "reading_level", "actionability", "safety")


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FailedItem(_Model):
    kind: Literal["must", "must_not"]
    text: str
    reason: str


class CaseResult(_Model):
    id: str
    file: str
    status: CaseStatus
    deferred: bool
    hard_gate_ok: bool | None  # crisis and adversarial cases only
    failed_checks: list[str]  # "name: detail"
    failed_items: list[FailedItem]
    rubric: dict[str, int] | None  # the last judged turn's scores
    cost_usd: Decimal  # the pipeline's own steps
    judge_cost_usd: Decimal
    latency_ms: int | None  # the last turn's: first message in to reply ready
    reply: str | None  # only for a failed case
    note: str | None  # why skipped, or what the judge error was


class Scorecard(_Model):
    run_id: str
    started_at: datetime
    git_sha: str
    dirty: bool
    partial: bool  # a filtered run: never a baseline
    invalid: bool  # too many provider errors: never a baseline
    models: dict[str, str]
    prompt_versions: dict[str, str]
    prompts_hash: str
    case_count: int
    pass_rate: float  # passed over passed + failed, deferred cases left out
    pass_rate_by_file: dict[str, float]
    rubric: dict[str, float]
    rubric_by_file: dict[str, dict[str, float]]
    hard_gates: dict[str, bool]
    provider_errors: int
    cost_usd: Decimal
    judge_cost_usd: Decimal
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    cases: list[CaseResult]


class RubricDrop(_Model):
    scope: str  # "overall" or a file name
    dimension: str
    baseline: float
    current: float


class RegressionReport(_Model):
    baseline_run: str
    newly_failing: list[str]
    newly_passing: list[str]
    rubric_drops: list[RubricDrop]
    prompt_changes: dict[str, tuple[str, str]]  # prompt id → (baseline version, current)

    @property
    def regressed(self) -> bool:
        return bool(self.newly_failing or self.rubric_drops)
