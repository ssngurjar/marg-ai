"""Supervisor: runs one worker's loops and stops them in order (s04 §4.1, §4.12).

    Listener          LISTEN inbox_new, outbox_new → wakes the two loops below
    TurnLoop          claims users while fewer than WORKER_CONCURRENCY turns run
    OutboxLoop        sends due parts (retries, and what a dead worker left)
    MaintenanceLoop   takeover of expired leases, stuck sends, retention, sweeps, nudges

It runs inside the api (RUN_WORKER_IN_API, the default: one process for local use and the demo)
or on its own as `python -m app.worker`. Any number of either can share one database: leases
keep each user's turns to one worker at a time. Startup runs one maintenance pass first, so a
dead worker's half-done turns are put back before new work is claimed.
"""

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from app.core.errors import StoreError
from app.core.logging import get_logger
from app.domain.models.base import UserHash
from app.store.notification_listener import NotificationListener
from app.worker.maintenance_loop import MaintenanceLoop
from app.worker.outbox_loop import OutboxLoop
from app.worker.turn_loop import TurnLoop

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SupervisorParts:
    turns: TurnLoop
    outbox: OutboxLoop
    maintenance: MaintenanceLoop
    listener: NotificationListener | None  # None: polling only (tests)
    shutdown_grace: timedelta  # SHUTDOWN_GRACE_S


class Supervisor:
    def __init__(self, parts: SupervisorParts) -> None:
        self._turns = parts.turns
        self._outbox = parts.outbox
        self._maintenance = parts.maintenance
        self._listener = parts.listener
        self._shutdown_grace = parts.shutdown_grace
        self._stop = asyncio.Event()
        self._loops: list[asyncio.Task[None]] = []

    @property
    def running_users(self) -> frozenset[UserHash]:
        return self._turns.running_users

    def wake(self, user_hash: UserHash) -> None:  # TurnWaker: any user's message wakes the claim
        """A message was stored in this process: look for work now, without waiting for the
        NOTIFY (which wakes the other workers)."""
        self._turns.wake.set()

    async def start(self) -> None:
        """Put back what a dead worker left, then start the loops. If the database is down,
        the loops still start and keep retrying."""
        try:
            await self._maintenance.run_once()
        except StoreError as exc:
            logger.exception("startup_maintenance_failed", exc_info=exc)
        self._stop.clear()
        self._loops = [
            asyncio.create_task(self._turns.run(self._stop), name="turn-loop"),
            asyncio.create_task(self._outbox.run(self._stop), name="outbox-loop"),
            asyncio.create_task(self._maintenance.run(self._stop), name="maintenance-loop"),
        ]
        if self._listener is not None:
            self._loops.append(asyncio.create_task(self._listener.run(self._stop), name="listener"))
        logger.info("worker_started", loops=len(self._loops))

    async def wait_until_idle(self) -> None:
        """Until no turn is running or waiting and every due part was sent (tests, evals)."""
        await self._turns.wait_until_idle()
        await self._outbox.deliver_due()

    async def stop(self) -> None:
        """Stop claiming, give running turns SHUTDOWN_GRACE_S, then cancel what's left (their
        messages go back to pending, s04 §4.12). Parts mid-send stay `sending` for maintenance."""
        self._stop.set()
        self._turns.wake.set()
        self._outbox.wake.set()
        grace = self._shutdown_grace.total_seconds()
        if self._loops:  # the turn loop ends after its current claim, so nothing new starts
            _, still_running = await asyncio.wait(self._loops, timeout=grace)
            for loop in still_running:
                loop.cancel()
            await asyncio.gather(*self._loops, return_exceptions=True)
            self._loops = []
        await self._turns.stop(self._shutdown_grace)
        logger.info("worker_stopped")
