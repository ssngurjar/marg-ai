"""The production StepRecorder (contracts §3): pipeline step results → turn_steps rows."""

from datetime import datetime
from decimal import Decimal

from app.domain.enums import Route, SafetyDecision, StepName, StepOutcome
from app.domain.models import TurnId
from app.pipeline.steps import StepFailure, StepUsage
from app.store.repositories.turn_steps import StepRow, TurnStepStore


class DatabaseStepRecorder:
    def __init__(self, store: TurnStepStore) -> None:
        self._store = store

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
        await self._store.insert(
            StepRow(
                turn_id=turn_id,
                step=step,
                outcome=outcome,
                failure_kind=failure.kind if failure else None,
                decision=decision,
                detail=detail if detail is not None else (failure.detail if failure else None),
                provider=usage.provider if usage else None,
                model=usage.model if usage else None,
                input_tokens=usage.input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
                audio_seconds=usage.audio_seconds if usage else None,
                cost_usd=usage.cost_usd if usage else Decimal(0),
                started_at=started_at,
                duration_ms=duration_ms,
            )
        )

    async def set_turn_text(self, turn_id: TurnId, user_text: str) -> None:
        await self._store.set_turn_text(turn_id, user_text)

    async def set_turn_route(self, turn_id: TurnId, route: Route) -> None:
        await self._store.set_turn_route(turn_id, route)
