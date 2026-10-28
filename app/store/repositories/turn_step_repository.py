"""turn_steps rows and the turn columns written while a turn runs (s04 §4.6).

Each write is its own short transaction, outside the turn's finalize: the steps are telemetry,
and an abandoned turn's steps stay because they happened. Each write notifies `turn_progress`,
so the web trace updates live. The worker's step recorder maps the pipeline's types onto
`StepRow`.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import StoreError
from app.domain.enums import FailureKind, Route, SafetyDecision, StepName, StepOutcome
from app.domain.models.base import TurnId
from app.store.tables import turn_steps, turns
from app.store.turn_progress_notifier import TurnProgressNotifier


@dataclass(frozen=True, slots=True)
class StepRow:
    turn_id: TurnId
    step: StepName
    outcome: StepOutcome
    failure_kind: FailureKind | None
    decision: SafetyDecision | None
    detail: str | None  # fixed vocabulary only
    provider: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    audio_seconds: Decimal | None
    cost_usd: Decimal
    started_at: datetime
    duration_ms: int


class TurnStepRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def insert(self, row: StepRow) -> None:
        values = {
            "turn_id": row.turn_id,
            "step": row.step.value,
            "outcome": row.outcome.value,
            "failure_kind": row.failure_kind.value if row.failure_kind else None,
            "decision": row.decision.value if row.decision else None,
            "detail": row.detail,
            "provider": row.provider,
            "model": row.model,
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "audio_seconds": row.audio_seconds,
            "cost_usd": row.cost_usd,
            "started_at": row.started_at,
            "duration_ms": row.duration_ms,
        }
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(turn_steps.insert().values(values))
                await TurnProgressNotifier.notify(session, row.turn_id)
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not record a turn step: {type(exc).__name__}") from exc

    async def set_turn_text(self, turn_id: TurnId, user_text: str) -> None:
        await self._update_turn(turn_id, user_text=user_text)

    async def set_turn_route(self, turn_id: TurnId, route: Route) -> None:
        await self._update_turn(turn_id, route=route.value)

    async def _update_turn(self, turn_id: TurnId, **values: object) -> None:
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(update(turns).where(turns.c.id == turn_id).values(values))
                await TurnProgressNotifier.notify(session, turn_id)
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not update the turn: {type(exc).__name__}") from exc
