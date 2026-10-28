"""TurnLoop: claims users and runs their turns, several at once (s04 §4.1 to §4.3, §4.8).

Any number of workers can run this loop against one database. A user's turn runs only under
that user's lease, so their turns stay one at a time and in order, whichever worker takes them.
A claim waits TURN_DEBOUNCE_MS after the user's newest message, so a burst becomes one turn.

While a turn runs, a heartbeat renews the lease every third of its length. When the lease can't
be renewed (this worker stalled and maintenance judged it dead), the turn is cancelled, and the
worker that takes over answers instead. After finalize the runner sends the reply at once (the
outbox loop retries what fails), starts post-turn work in the background, and wakes the loop:
the user may have written again meanwhile.
"""

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from app.core.errors import StoreError
from app.core.logging import get_logger
from app.domain.models.base import TurnId, UserHash
from app.store.repositories.lease_repository import LeaseRepository
from app.worker.post_turn_runner import PostTurnRunner
from app.worker.reply_deliverer import ReplyDeliverer
from app.worker.turn_processor import TurnProcessor

HEARTBEATS_PER_LEASE: Final = 3
SHORTEST_IDLE_CHECK: Final = timedelta(milliseconds=20)

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TurnLoopSettings:
    worker_id: str
    concurrency: int  # WORKER_CONCURRENCY: turns running at once in this worker
    lease: timedelta  # LEASE_DURATION_S: the heartbeat renews every third of it
    poll_interval: timedelta  # POLL_INTERVAL_S: looks for work this often without a NOTIFY
    error_backoff: timedelta  # the wait after a database error


@dataclass(frozen=True, slots=True)
class TurnLoopDeps:
    processor: TurnProcessor
    deliverer: ReplyDeliverer
    leases: LeaseRepository
    post_turn: PostTurnRunner  # signals, memory and cards, after the reply is sent


class TurnLoop:
    def __init__(self, deps: TurnLoopDeps, settings: TurnLoopSettings) -> None:
        self._processor = deps.processor
        self._deliverer = deps.deliverer
        self._leases = deps.leases
        self._post_turn_runner = deps.post_turn
        self._settings = settings
        self._running: dict[UserHash, asyncio.Task[None]] = {}
        self._post_turn_jobs: set[asyncio.Task[None]] = set()
        self.wake = asyncio.Event()  # a message arrived (NOTIFY inbox_new, or this process)

    @property
    def running_users(self) -> frozenset[UserHash]:
        return frozenset(self._running)

    async def run(self, stop: asyncio.Event) -> None:
        """Claim users while there's room, until `stop` is set (the caller also sets `wake`,
        so the wait ends at once)."""
        while not stop.is_set():
            self.wake.clear()
            try:
                await self.claim_available()
                pause = self._settings.poll_interval
            except StoreError as exc:
                logger.exception("turn_claim_failed", exc_info=exc)
                pause = self._settings.error_backoff
            await _wait_for(self.wake, pause)

    async def claim_available(self) -> int:
        """Claim users and start their turns until this worker is full or nobody is waiting.
        Returns how many turns were started."""
        started = 0
        while len(self._running) < self._settings.concurrency:
            user_hash = await self._leases.claim_user(self._settings.worker_id)
            if user_hash is None:
                break
            self._start(user_hash)
            started += 1
        return started

    async def wait_until_idle(self) -> None:
        """Run turns until nothing is left: none running, no post-turn work, and no pending
        message, including those still inside their backoff or burst window (tests, evals).
        Messages for a user whose lease another worker holds are waited for too."""
        while True:
            busy = [*self._running.values(), *self._post_turn_jobs]
            if busy:
                await asyncio.gather(*busy, return_exceptions=True)
                continue
            if await self.claim_available():
                continue
            until = await self._leases.until_claimable()
            if until is None:
                return
            await asyncio.sleep(max(until, SHORTEST_IDLE_CHECK).total_seconds())

    async def stop(self, grace: timedelta) -> None:
        """Let running turns and post-turn work finish within `grace`, then cancel the rest. A
        cancelled turn puts its messages back without counting an attempt (s04 §4.12)."""
        running = [*self._running.values(), *self._post_turn_jobs]
        if not running:
            return
        _, still_running = await asyncio.wait(running, timeout=grace.total_seconds())
        for task in still_running:
            task.cancel()
        await asyncio.gather(*still_running, return_exceptions=True)
        logger.info("turn_loop_stopped", cancelled=len(still_running))

    def _start(self, user_hash: UserHash) -> None:
        task = asyncio.create_task(self._serve(user_hash), name=f"turn-{user_hash[:8]}")
        self._running[user_hash] = task
        task.add_done_callback(lambda finished: self._finished(user_hash, finished))

    def _finished(self, user_hash: UserHash, finished: asyncio.Task[None]) -> None:
        if self._running.get(user_hash) is finished:
            del self._running[user_hash]
        self.wake.set()  # room for another user, and this one may have written again

    async def _serve(self, user_hash: UserHash) -> None:
        try:
            turn_id = await self._run_under_lease(user_hash)
            if turn_id is None:
                return
            await self._deliverer.deliver_turn(turn_id)
            self._start_post_turn(turn_id)
        except StoreError as exc:
            # The lease expires and maintenance puts any half-done turn back (s04 §4.14).
            logger.exception("turn_store_error", user_task=user_hash[:8], exc_info=exc)

    async def _run_under_lease(self, user_hash: UserHash) -> TurnId | None:
        """One turn with its heartbeat. None when there was nothing to run (the lease is given
        back) or the lease was lost (the worker that took over answers)."""
        turn = asyncio.create_task(self._processor.process_user_turn(user_hash))
        heartbeat = asyncio.create_task(self._heartbeat(user_hash, turn))
        try:
            turn_id = await turn
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise  # shutdown: the processor already put the messages back
            logger.warning("lease_lost", user_task=user_hash[:8])
            return None
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        if turn_id is None:
            await self._leases.release(user_hash, self._settings.worker_id)
        return turn_id

    async def _heartbeat(self, user_hash: UserHash, turn: "asyncio.Task[TurnId | None]") -> None:
        every = self._settings.lease / HEARTBEATS_PER_LEASE
        while not turn.done():
            await asyncio.sleep(every.total_seconds())
            try:
                renewed = await self._leases.renew(user_hash, self._settings.worker_id)
            except StoreError as exc:
                # Two more beats before the lease runs out: try again at the next one.
                logger.warning("lease_renew_failed", user_task=user_hash[:8], exc_info=exc)
                continue
            if not renewed:
                turn.cancel()
                return

    def _start_post_turn(self, turn_id: TurnId) -> None:
        """Signals and other after-the-reply work, in the background: the user's next message
        doesn't wait for it. Shutdown waits for what's running (stop)."""
        tasks = self._processor.take_post_turn(turn_id)
        if not tasks:
            return
        job = asyncio.create_task(self._post_turn_runner.run(tasks), name="post-turn")
        self._post_turn_jobs.add(job)
        job.add_done_callback(self._post_turn_jobs.discard)


async def _wait_for(event: asyncio.Event, longest: timedelta) -> None:
    try:
        await asyncio.wait_for(event.wait(), timeout=longest.total_seconds())
    except TimeoutError:
        return
