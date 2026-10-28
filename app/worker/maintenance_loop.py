"""MaintenanceLoop: the periodic jobs that keep the queue healthy (s04 §4.13).

Every MAINTENANCE_INTERVAL_S, in order, each in its own transaction and each idempotent, so
several workers can run it at once: take over expired leases (fail the dead turn, put its
messages back), reset parts stuck in `sending`, retention, the purge sweep, expired media,
old rate-limit windows, abandoned child sessions and their parents' summaries, and the daily nudges.
"""

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from app.core.clock import Clock
from app.core.errors import StoreError
from app.core.logging import get_logger
from app.store.repositories.child_session_repository import ChildSessionRepository
from app.store.repositories.demo_repository import DemoRepository
from app.store.repositories.lease_repository import LeaseRepository
from app.store.repositories.media_blob_repository import MediaBlobRepository
from app.store.repositories.outbox_repository import OutboxRepository
from app.store.repositories.turn_repository import TurnRepository
from app.store.repositories.user_repository import UserRepository
from app.worker.child_session_summary_sender import ChildSessionSummarySender
from app.worker.nudge_sender import NudgeSender

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class MaintenanceSettings:
    interval: timedelta  # MAINTENANCE_INTERVAL_S
    sending_stuck: timedelta  # OUTBOX_SENDING_STUCK_S
    retain_turn_text: timedelta  # RETENTION_TURN_TEXT_DAYS
    retain_raw_payload: timedelta  # RETENTION_RAW_PAYLOAD_DAYS
    purge_sweep_after: timedelta  # PURGE_SWEEP_AFTER_S
    child_session_max: timedelta  # CHILD_SESSION_MAX_MINUTES: an open session past it is closed
    rate_limit_window_kept: timedelta = timedelta(days=2)  # s04 §4.13


@dataclass(frozen=True, slots=True)
class MaintenanceDeps:
    leases: LeaseRepository
    outbox: OutboxRepository
    turns: TurnRepository
    users: UserRepository
    media: MediaBlobRepository
    child_sessions: ChildSessionRepository
    summaries: ChildSessionSummarySender  # for sessions the child left without a goodbye
    demo: DemoRepository  # the web demo's rate-limit counters
    nudges: NudgeSender | None  # the daily khoj message; None while NUDGES_ENABLED is false
    clock: Clock


class MaintenanceLoop:
    def __init__(self, deps: MaintenanceDeps, settings: MaintenanceSettings) -> None:
        self._deps = deps
        self._settings = settings

    async def run(self, stop: asyncio.Event) -> None:
        """One pass every interval until `stop` is set (the first pass runs at startup)."""
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._settings.interval.total_seconds())
            except TimeoutError:
                pass
            else:
                return
            try:
                await self.run_once()
            except StoreError as exc:
                logger.exception("maintenance_failed", exc_info=exc)

    async def run_once(self) -> None:
        """Raises StoreError when the database can't be reached; the next pass tries again."""
        deps = self._deps
        takeover = await deps.leases.take_over_expired()
        if takeover.leases or takeover.turns:
            logger.warning(
                "leases_taken_over",
                leases=takeover.leases,
                turns=takeover.turns,
                messages=takeover.messages,
            )
        reset = await deps.outbox.reset_stuck_sending(self._settings.sending_stuck)
        if reset:
            # A part Meta had already accepted is sent again: the one duplicate (s04 §4.10).
            logger.warning("outbox_resend_after_stuck", parts=reset)
        now = deps.clock.now()
        cleared = await deps.turns.clear_expired_text(
            turn_text_before=now - self._settings.retain_turn_text,
            raw_payload_before=now - self._settings.retain_raw_payload,
        )
        if cleared:
            logger.info("retention_cleared", rows=cleared)
        purged = await deps.users.sweep_purges(self._settings.purge_sweep_after)
        if purged:
            logger.info("purge_sweep", users=purged)
        expired_media = await deps.media.delete_expired()
        if expired_media:
            logger.info("media_expired", blobs=expired_media)
        abandoned = await deps.child_sessions.close_abandoned(self._settings.child_session_max)
        if abandoned:
            logger.info("child_sessions_expired", sessions=abandoned)
        summaries = await deps.summaries.send_due()
        if summaries:
            logger.info("child_session_summaries_sent", parents=summaries)
        pruned = await deps.demo.prune_rate_limits(self._settings.rate_limit_window_kept)
        if pruned:
            logger.info("rate_limits_pruned", windows=pruned)
        if deps.nudges is not None:
            nudged = await deps.nudges.send_due()
            if nudged:
                logger.info("nudges_sent", parents=nudged)
