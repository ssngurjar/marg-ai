"""One turn for one user, start to finish (s04 §4.4 to §4.9; contracts §3 `process_user_turn`).

The dispatcher calls this for production turns and S15's eval runner calls it directly, so evals
exercise exactly the production path. Exception E1: one process holds the user's lock, so there
is no lease or heartbeat.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from app.core.clock import Clock
from app.core.errors import ChannelError, ProviderError
from app.core.logging import get_logger
from app.domain.enums import Channel, FixedReplyKind, InboxStatus
from app.domain.models import TurnContext, TurnId, UserHash
from app.domain.turns import is_poisoned, is_stale, turn_retry_delay
from app.pipeline.fallbacks import FixedReplyVariant, localise_fixed
from app.pipeline.orchestrator import NullTurnObserver
from app.pipeline.parts import build_parts
from app.pipeline.steps import StepRecorder, TurnObserver, TurnOutcome
from app.providers.ports import ChannelSender
from app.safety.gate import SafetyGate
from app.store.repositories.turns import FinishedTurn, StartedTurn, TurnStore

type RunTurn = Callable[[TurnContext, StepRecorder, TurnObserver], Awaitable[TurnOutcome]]

PRODUCTION_OBSERVER: Final = NullTurnObserver()

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TurnSettings:
    worker_id: str
    max_messages: int  # MAX_MESSAGES_PER_TURN
    max_attempts: int  # MAX_TURN_ATTEMPTS
    stale_after: timedelta  # STALE_MESSAGE_HOURS
    recent_exchanges: int  # RECENT_EXCHANGES


@dataclass(frozen=True, slots=True)
class TurnDeps:
    store: TurnStore
    recorder: StepRecorder
    run_turn: RunTurn
    gate: SafetyGate
    senders: Mapping[Channel, ChannelSender]  # for acknowledge (read receipt + typing)
    clock: Clock


class TurnProcessor:
    def __init__(self, deps: TurnDeps, settings: TurnSettings) -> None:
        self._store = deps.store
        self._recorder = deps.recorder
        self._run_turn = deps.run_turn
        self._gate = deps.gate
        self._senders = deps.senders
        self._clock = deps.clock
        self._settings = settings

    async def process_user_turn(
        self, user_hash: UserHash, observer: TurnObserver = PRODUCTION_OBSERVER
    ) -> TurnId | None:
        """Run one turn over this user's due pending messages. None when nothing was due.

        Poisoned and stale batches are finalized without calling the pipeline. A pipeline that
        raises (a bug) fails the turn and puts its messages back with backoff; it never answers.
        """
        started = await self._store.start_turn(
            user_hash, self._settings.max_messages, self._settings.worker_id
        )
        if started is None:
            return None
        if is_poisoned(started.queued, self._settings.max_attempts):
            await self._finalize_poisoned(started)
        elif is_stale(started.queued, self._clock.now(), self._settings.stale_after):
            await self._finalize_stale(started)
        else:
            await self._run(started, observer)
        return started.turn_id

    async def _run(self, started: StartedTurn, observer: TurnObserver) -> None:
        try:
            context = await self._store.load_context(started, self._settings.recent_exchanges)
            await self._acknowledge(started)
            outcome = await self._run_turn(context, self._recorder, observer)
        except asyncio.CancelledError:
            # Shutdown: a deploy isn't the message's fault, so the attempt doesn't count.
            await self._store.abandon(started, count_attempt=False, retry_after=timedelta(0))
            raise
        except Exception as exc:  # the turn boundary (s04 §4.9): record, back off, retry
            attempts = max(queued.attempts for queued in started.queued)
            await self._store.abandon(
                started, count_attempt=True, retry_after=turn_retry_delay(attempts)
            )
            logger.exception(
                "turn_crashed",
                turn_id=str(started.turn_id),
                attempts=attempts + 1,
                exc_info=exc,
            )
            return
        await self._store.finalize(started, _finished(outcome), outcome.delivery)

    async def _acknowledge(self, started: StartedTurn) -> None:
        """Blue ticks and "typing…" for the newest message. Best effort: never stops the turn."""
        sender = self._senders.get(started.channel)
        if sender is None:
            return
        newest = started.queued[-1].message
        try:
            await sender.acknowledge(newest.external_id)
        except (ProviderError, ChannelError) as exc:
            logger.warning(
                "acknowledge_failed", turn_id=str(started.turn_id), error=type(exc).__name__
            )

    async def _finalize_poisoned(self, started: StartedTurn) -> None:
        """These messages have crashed MAX_TURN_ATTEMPTS turns: say so once, through the sealed
        fixed-reply path, and close them as failed."""
        kind = FixedReplyKind.TRY_AGAIN_LATER
        localised = localise_fixed(kind, FixedReplyVariant.DEFAULT, language=None)
        safe = self._gate.clear_fixed(localised, kind)
        finished = FinishedTurn(
            route=None,
            fixed_reply_kind=kind,
            user_text=None,
            reply_text=safe.text,
            reply_register=safe.reply_register,
            prompt_versions={},
            failure_step=None,
            failure_kind=None,
            inbox_status=InboxStatus.FAILED,
        )
        await self._store.finalize(started, finished, build_parts(safe, audio_blob_id=None))
        logger.error("turn_poisoned", turn_id=str(started.turn_id), messages=len(started.queued))

    async def _finalize_stale(self, started: StartedTurn) -> None:
        """Every message is too old to answer (WhatsApp's window has closed): close them quietly."""
        finished = FinishedTurn(
            route=None,
            fixed_reply_kind=None,
            user_text=None,
            reply_text=None,
            reply_register=None,
            prompt_versions={},
            failure_step=None,
            failure_kind=None,
            inbox_status=InboxStatus.DONE,
        )
        await self._store.finalize(started, finished, delivery=None)
        logger.info("turn_stale", turn_id=str(started.turn_id), messages=len(started.queued))


def _finished(outcome: TurnOutcome) -> FinishedTurn:
    failure = outcome.first_failure
    return FinishedTurn(
        route=outcome.route,
        fixed_reply_kind=outcome.fixed_reply_kind,
        user_text=outcome.user_text,
        reply_text=outcome.reply_text,
        reply_register=outcome.reply_register,
        prompt_versions=outcome.prompt_versions,
        failure_step=failure.step if failure else None,
        failure_kind=failure.kind if failure else None,
        inbox_status=InboxStatus.DONE,
    )
