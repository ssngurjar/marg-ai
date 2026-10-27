"""The two hooks every step reports through (contracts §3): StepRecorder and TurnObserver.

They live in the pipeline rather than providers/ports.py because their arguments are pipeline
models, and ports may not import the pipeline (s04 decisions log, 2026-10-27).
"""

from datetime import datetime
from typing import Protocol

from app.domain.enums import Route, SafetyDecision, StepName, StepOutcome
from app.domain.models.base import TurnId
from app.pipeline.step_models import StepFailure, StepSuccess, StepUsage


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
