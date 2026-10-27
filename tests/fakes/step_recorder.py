"""A StepRecorder that keeps rows in memory, optionally failing like a down database."""

from dataclasses import dataclass
from datetime import datetime

from app.core.errors import StoreError
from app.domain.enums import Route, SafetyDecision, StepName, StepOutcome
from app.domain.models.base import TurnId
from app.domain.models.usage import StepUsage
from app.pipeline.step_models import StepFailure


@dataclass(frozen=True, slots=True)
class RecordedStep:
    step: StepName
    outcome: StepOutcome
    detail: str | None
    decision: SafetyDecision | None
    failure: StepFailure | None
    usage: StepUsage | None


class MemoryStepRecorder:
    """Satisfies `StepRecorder`."""

    def __init__(self, *, fail: bool = False) -> None:
        self.steps: list[RecordedStep] = []
        self.turn_text: str | None = None
        self.turn_route: Route | None = None
        self._fail = fail

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
    ) -> None:
        if self._fail:
            raise StoreError("could not record a turn step: OperationalError")
        self.steps.append(RecordedStep(step, outcome, detail, decision, failure, usage))

    async def set_turn_text(self, turn_id: TurnId, user_text: str) -> None:
        if self._fail:
            raise StoreError("could not update the turn: OperationalError")
        self.turn_text = user_text

    async def set_turn_route(self, turn_id: TurnId, route: Route) -> None:
        if self._fail:
            raise StoreError("could not update the turn: OperationalError")
        self.turn_route = route

    def outcomes(self) -> list[tuple[StepName, StepOutcome]]:
        return [(row.step, row.outcome) for row in self.steps]
