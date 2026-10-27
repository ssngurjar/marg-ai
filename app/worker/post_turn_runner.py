"""PostTurnRunner: work after the reply is sent, off its critical path (s04 §4.16, s13 §4.2).

Curiosity signals (EXTRACT_SIGNALS), then a khoj card (MAKE_CARD, s10b §4.13) when one was asked
for: the card needs the signals' engagement, so tasks run in order. Each is recorded as a step
of the turn that asked for it; a failure never touches the reply, which has already gone out.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import assert_never

from app.core.clock import Clock
from app.core.errors import MediaError, ProviderError, SafetyUnavailable, StoreError
from app.core.logging import get_logger
from app.domain.enums import StepName, StepOutcome
from app.domain.models.curiosity import ExtractSignals, MakeKhojCard, PostTurnTask
from app.domain.models.usage import StepUsage
from app.pipeline.failure_policy import FailurePolicy
from app.pipeline.step_models import StepFailure
from app.pipeline.turn_protocols import StepRecorder
from app.store.repositories.curiosity_signal_repository import CuriositySignalRepository
from app.telemetry.curiosity_signal_extractor import CuriositySignalExtractor
from app.worker.khoj_card_sender import KhojCardSender

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PostTurnDeps:
    extractor: CuriositySignalExtractor
    signals: CuriositySignalRepository
    recorder: StepRecorder
    clock: Clock
    timeout: timedelta  # each task's limit
    cards: KhojCardSender | None  # None while KHOJ_CARD_ENABLED is false


class PostTurnRunner:
    def __init__(self, deps: PostTurnDeps) -> None:
        self._extractor = deps.extractor
        self._signals = deps.signals
        self._recorder = deps.recorder
        self._clock = deps.clock
        self._timeout = deps.timeout
        self._cards = deps.cards

    async def run(self, tasks: Sequence[PostTurnTask]) -> None:
        for task in tasks:
            match task:
                case ExtractSignals():
                    await self._extract(task)
                case MakeKhojCard():
                    await self._card(task)
                case _:
                    assert_never(task)

    async def _card(self, task: MakeKhojCard) -> None:
        if self._cards is None:
            return
        started = self._clock.now()
        try:
            async with asyncio.timeout(self._timeout.total_seconds()):
                outcome = await self._cards.send(task)
        except (ProviderError, SafetyUnavailable, MediaError, StoreError, TimeoutError) as exc:
            logger.warning("khoj_card_failed", turn_id=str(task.turn_id), exc_info=exc)
            failure = StepFailure(
                step=StepName.MAKE_CARD,
                kind=FailurePolicy.kind_of(exc),
                detail=type(exc).__name__,
                retryable=False,
            )
            await self._record(
                task, StepName.MAKE_CARD, started, StepOutcome.FAILED, _Recorded(failure=failure)
            )
            return
        result = StepOutcome.OK if outcome.sent else StepOutcome.SKIPPED
        recorded = _Recorded(detail=outcome.detail, usage=outcome.usage)
        await self._record(task, StepName.MAKE_CARD, started, result, recorded)

    async def _extract(self, task: ExtractSignals) -> None:
        started = self._clock.now()
        try:
            async with asyncio.timeout(self._timeout.total_seconds()):
                extracted = await self._extractor.extract(task)
            saved = await self._signals.save(task, extracted.signals, extracted.prompt_version)
        except (ProviderError, TimeoutError, StoreError) as exc:
            logger.warning("curiosity_extraction_failed", turn_id=str(task.turn_id), exc_info=exc)
            failure = StepFailure(
                step=StepName.EXTRACT_SIGNALS,
                kind=FailurePolicy.kind_of(exc),
                detail=type(exc).__name__,
                retryable=False,
            )
            await self._record(
                task,
                StepName.EXTRACT_SIGNALS,
                started,
                StepOutcome.FAILED,
                _Recorded(failure=failure),
            )
            return
        if not saved:
            await self._record(
                task,
                StepName.EXTRACT_SIGNALS,
                started,
                StepOutcome.SKIPPED,
                _Recorded(detail="user_gone"),
            )
            return
        signals = extracted.signals
        detail = (
            f"source={task.source.kind} engagement={signals.engagement}"
            f" asked={str(signals.child_asked_question).lower()}"
        )
        await self._record(
            task,
            StepName.EXTRACT_SIGNALS,
            started,
            StepOutcome.OK,
            _Recorded(detail=detail, usage=extracted.usage),
        )

    async def _record(
        self,
        task: PostTurnTask,
        step: StepName,
        started: datetime,
        outcome: StepOutcome,
        result: "_Recorded",
    ) -> None:
        """Telemetry about telemetry: a failed write is logged, never raised."""
        duration_ms = max(int((self._clock.now() - started).total_seconds() * 1000), 0)
        try:
            await self._recorder.record(
                turn_id=task.turn_id,
                step=step,
                outcome=outcome,
                started_at=started,
                duration_ms=duration_ms,
                usage=result.usage,
                failure=result.failure,
                detail=result.detail,
            )
        except StoreError as exc:
            logger.warning("post_turn_record_failed", turn_id=str(task.turn_id), exc_info=exc)


@dataclass(frozen=True, slots=True)
class _Recorded:
    detail: str | None = None
    failure: StepFailure | None = None
    usage: StepUsage | None = None
