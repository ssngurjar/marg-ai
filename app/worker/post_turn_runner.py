"""PostTurnRunner: work after the reply is sent, off its critical path (s04 §4.16, s13 §4.2).

Today: curiosity signal extraction. Each task is recorded as a turn step (EXTRACT_SIGNALS), and
a failure never touches the reply, which has already gone out.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.clock import Clock
from app.core.errors import ProviderError, StoreError
from app.core.logging import get_logger
from app.domain.enums import StepName, StepOutcome
from app.domain.models.curiosity import PostTurnTask
from app.domain.models.usage import StepUsage
from app.pipeline.failure_policy import FailurePolicy
from app.pipeline.step_models import StepFailure
from app.pipeline.turn_protocols import StepRecorder
from app.store.repositories.curiosity_signal_repository import CuriositySignalRepository
from app.telemetry.curiosity_signal_extractor import CuriositySignalExtractor

logger = get_logger(__name__)


class PostTurnRunner:
    def __init__(
        self,
        extractor: CuriositySignalExtractor,
        signals: CuriositySignalRepository,
        recorder: StepRecorder,
        clock: Clock,
        timeout: timedelta,
    ) -> None:
        self._extractor = extractor
        self._signals = signals
        self._recorder = recorder
        self._clock = clock
        self._timeout = timeout

    async def run(self, tasks: Sequence[PostTurnTask]) -> None:
        for task in tasks:
            await self._extract(task)

    async def _extract(self, task: PostTurnTask) -> None:
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
            await self._record(task, started, StepOutcome.FAILED, _Recorded(failure=failure))
            return
        if not saved:
            await self._record(task, started, StepOutcome.SKIPPED, _Recorded(detail="user_gone"))
            return
        signals = extracted.signals
        detail = (
            f"source={task.source.kind} engagement={signals.engagement}"
            f" asked={str(signals.child_asked_question).lower()}"
        )
        await self._record(
            task, started, StepOutcome.OK, _Recorded(detail=detail, usage=extracted.usage)
        )

    async def _record(
        self,
        task: PostTurnTask,
        started: datetime,
        outcome: StepOutcome,
        result: "_Recorded",
    ) -> None:
        """Telemetry about telemetry: a failed write is logged, never raised."""
        duration_ms = max(int((self._clock.now() - started).total_seconds() * 1000), 0)
        try:
            await self._recorder.record(
                turn_id=task.turn_id,
                step=StepName.EXTRACT_SIGNALS,
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
