"""OutboxLoop: sends queued parts whose time has come (s04 §4.10).

A turn's runner sends its reply straight after finalize; this loop sends what that didn't: parts
whose retry time has come, parts reset after a dead worker left them `sending`, and parts queued
by a worker that died before sending. Several workers can run it at once: claiming a part locks
its turn's rows, and a turn's parts still go strictly in order.
"""

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from itertools import batched

from app.core.errors import StoreError
from app.core.logging import get_logger
from app.domain.models.base import TurnId
from app.store.repositories.outbox_repository import OutboxRepository
from app.worker.reply_deliverer import ReplyDeliverer

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class OutboxLoopSettings:
    concurrency: int  # OUTBOX_CONCURRENCY: turns sent at once
    poll_interval: timedelta  # POLL_INTERVAL_S
    error_backoff: timedelta


class OutboxLoop:
    def __init__(
        self, outbox: OutboxRepository, deliverer: ReplyDeliverer, settings: OutboxLoopSettings
    ) -> None:
        self._outbox = outbox
        self._deliverer = deliverer
        self._settings = settings
        self.wake = asyncio.Event()  # a part was queued (NOTIFY outbox_new)

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            self.wake.clear()
            try:
                await self.deliver_due()
                pause = self._settings.poll_interval
            except StoreError as exc:
                logger.exception("outbox_pass_failed", exc_info=exc)
                pause = self._settings.error_backoff
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=pause.total_seconds())
            except TimeoutError:
                continue

    async def deliver_due(self) -> int:
        """Send every due part, a few turns at a time. Returns how many parts were sent."""
        turn_ids = await self._outbox.turns_with_due_parts()
        sent = 0
        for group in batched(turn_ids, self._settings.concurrency, strict=False):
            counts = await asyncio.gather(*(self._deliver(turn_id) for turn_id in group))
            sent += sum(counts)
        return sent

    async def _deliver(self, turn_id: TurnId) -> int:
        try:
            return await self._deliverer.deliver_turn(turn_id)
        except StoreError as exc:  # this turn waits for the next pass; the others go on
            logger.exception("outbox_turn_failed", turn_id=str(turn_id), exc_info=exc)
            return 0
