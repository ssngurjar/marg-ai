"""The in-process turn dispatcher (exception E1, mvp-scope §4.1).

One asyncio task per user with pending messages, so a user's turns run one at a time, in order.
A wake-up waits TURN_DEBOUNCE_MS first, so a burst of messages becomes one turn. At startup,
work a dead process left half-done is put back and resumed; a maintenance pass sends parts whose
retry time has come, wakes users whose backoff has passed and applies retention.

E1's upgrade (s04 §4.1: leases, a separate worker process, LISTEN/NOTIFY) replaces this module;
`TurnProcessor` and `ReplyDeliverer` stay as they are.
"""

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from app.core.clock import Clock
from app.core.errors import StoreError
from app.core.logging import get_logger
from app.domain.models.base import TurnId, UserHash
from app.store.repositories.child_session_repository import ChildSessionRepository
from app.store.repositories.media_blob_repository import MediaBlobRepository
from app.store.repositories.outbox_repository import OutboxRepository
from app.store.repositories.turn_repository import TurnRepository
from app.store.repositories.user_repository import UserRepository
from app.worker.nudge_sender import NudgeSender
from app.worker.reply_deliverer import ReplyDeliverer
from app.worker.turn_processor import TurnProcessor

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DispatcherSettings:
    debounce: timedelta  # TURN_DEBOUNCE_MS
    maintenance_interval: timedelta  # MAINTENANCE_INTERVAL_S
    shutdown_grace: timedelta  # SHUTDOWN_GRACE_S
    retain_turn_text: timedelta  # RETENTION_TURN_TEXT_DAYS
    retain_raw_payload: timedelta  # RETENTION_RAW_PAYLOAD_DAYS
    purge_sweep_after: timedelta  # PURGE_SWEEP_AFTER_S
    child_session_max: timedelta  # CHILD_SESSION_MAX_MINUTES: an open session past it is closed
    error_backoff: timedelta  # wait after a database error before trying the user again


@dataclass(frozen=True, slots=True)
class DispatcherDeps:
    processor: TurnProcessor
    deliverer: ReplyDeliverer
    turns: TurnRepository
    outbox: OutboxRepository
    users: UserRepository
    clock: Clock
    media: MediaBlobRepository  # expired reply audio is deleted by the maintenance pass
    child_sessions: ChildSessionRepository  # sessions a child left mid-way are closed
    nudges: NudgeSender | None  # the daily khoj message; None while NUDGES_ENABLED is false


class TurnDispatcher:
    def __init__(self, deps: DispatcherDeps, settings: DispatcherSettings) -> None:
        self._processor = deps.processor
        self._deliverer = deps.deliverer
        self._turns = deps.turns
        self._outbox = deps.outbox
        self._users = deps.users
        self._media = deps.media
        self._child_sessions = deps.child_sessions
        self._nudges = deps.nudges
        self._clock = deps.clock
        self._settings = settings
        self._user_tasks: dict[UserHash, asyncio.Task[None]] = {}
        self._woken: dict[UserHash, asyncio.Event] = {}
        self._maintenance: asyncio.Task[None] | None = None
        self._stopping = False
        self._recovered = False

    @property
    def running_users(self) -> frozenset[UserHash]:
        return frozenset(self._user_tasks)

    async def start(self) -> None:
        """Recover what a dead process left and resume it, then start the maintenance pass.

        If the database is down at startup, the app still starts: the failure is logged and
        each maintenance pass retries the recovery until it succeeds.
        """
        try:
            await self._recover()
        except StoreError as exc:
            logger.exception("dispatcher_recovery_failed", exc_info=exc)
        self._maintenance = asyncio.create_task(self._maintain(), name="turn-maintenance")

    async def _recover(self) -> None:
        requeued = await self._turns.recover_unfinished(retry_after=timedelta(0))
        reset = await self._outbox.reset_sending()
        if reset:
            # A part Meta had already accepted before the crash is sent again (s04 §4.10).
            logger.warning("outbox_resend_after_restart", parts=reset)
        logger.info("dispatcher_recovered", messages_requeued=requeued, parts_reset=reset)
        self._recovered = True
        await self._deliver_due_parts()
        for user_hash in await self._turns.users_with_pending():
            self.wake(user_hash)

    def wake(self, user_hash: UserHash) -> None:
        """A message for this user was stored: run a turn soon (after the debounce)."""
        if self._stopping:
            return
        event = self._woken.setdefault(user_hash, asyncio.Event())
        event.set()
        current = self._user_tasks.get(user_hash)
        if current is not None and not current.done():
            return  # the running task sees the event and serves this message too
        task = asyncio.create_task(self._serve_user(user_hash), name=f"turns-{user_hash[:8]}")
        self._user_tasks[user_hash] = task
        task.add_done_callback(lambda finished: self._forget(user_hash, finished))

    def _forget(self, user_hash: UserHash, finished: asyncio.Task[None]) -> None:
        if self._user_tasks.get(user_hash) is finished:
            del self._user_tasks[user_hash]

    async def wait_until_idle(self) -> None:
        """Wait until no user has a turn running or waiting (tests and orderly shutdown)."""
        while self._user_tasks:
            await asyncio.gather(*self._user_tasks.values(), return_exceptions=True)

    async def stop(self) -> None:
        """Stop taking work; let running turns finish within the grace period, then cancel them
        (a cancelled turn puts its messages back without counting an attempt)."""
        self._stopping = True
        if self._maintenance is not None:
            self._maintenance.cancel()
            await asyncio.gather(self._maintenance, return_exceptions=True)
        running = list(self._user_tasks.values())
        if not running:
            return
        _, still_running = await asyncio.wait(
            running, timeout=self._settings.shutdown_grace.total_seconds()
        )
        for task in still_running:
            task.cancel()
        await asyncio.gather(*still_running, return_exceptions=True)
        logger.info("dispatcher_stopped", cancelled_turns=len(still_running))

    async def _serve_user(self, user_hash: UserHash) -> None:
        """Run this user's turns one after another until nothing is pending."""
        woken = self._woken[user_hash]
        while not self._stopping:
            woken.clear()
            await asyncio.sleep(self._settings.debounce.total_seconds())
            try:
                turn_id = await self._processor.process_user_turn(user_hash)
                if turn_id is not None:
                    await self._deliverer.deliver_turn(turn_id)
                    continue
                wait = await self._wait_for_next_pending(user_hash)
            except StoreError as exc:
                logger.exception("dispatcher_store_error", user_task=user_hash[:8], exc_info=exc)
                wait = self._settings.error_backoff
            if wait is None:
                if woken.is_set():
                    continue  # a message arrived while we checked: serve it now
                return
            await self._sleep_unless_woken(woken, wait)

    async def _wait_for_next_pending(self, user_hash: UserHash) -> timedelta | None:
        """How long until this user's next pending message is due; None if none is pending."""
        due_at = await self._turns.next_pending_at(user_hash)
        if due_at is None:
            return None
        return max(due_at - self._clock.now(), timedelta(0))

    async def _sleep_unless_woken(self, woken: asyncio.Event, wait: timedelta) -> None:
        try:
            await asyncio.wait_for(woken.wait(), timeout=wait.total_seconds())
        except TimeoutError:
            return

    async def _maintain(self) -> None:
        interval = self._settings.maintenance_interval.total_seconds()
        while True:
            await asyncio.sleep(interval)
            try:
                await self._maintenance_pass()
            except StoreError as exc:
                logger.exception("maintenance_failed", exc_info=exc)

    async def _maintenance_pass(self) -> None:
        if not self._recovered:
            await self._recover()
            return
        await self._deliver_due_parts()
        for user_hash in await self._turns.users_with_pending():
            if user_hash not in self._user_tasks:
                self.wake(user_hash)
        now = self._clock.now()
        cleared = await self._turns.clear_expired_text(
            turn_text_before=now - self._settings.retain_turn_text,
            raw_payload_before=now - self._settings.retain_raw_payload,
        )
        if cleared:
            logger.info("retention_cleared", rows=cleared)
        purged = await self._users.sweep_purges(self._settings.purge_sweep_after)
        if purged:
            logger.info("purge_sweep", users=purged)
        expired_media = await self._media.delete_expired()
        if expired_media:
            logger.info("media_expired", blobs=expired_media)
        abandoned = await self._child_sessions.close_abandoned(self._settings.child_session_max)
        if abandoned:
            logger.info("child_sessions_expired", sessions=abandoned)
        if self._nudges is not None:
            nudged = await self._nudges.send_due()
            if nudged:
                logger.info("nudges_sent", parents=nudged)

    async def _deliver_due_parts(self) -> None:
        turn_ids: list[TurnId] = await self._outbox.turns_with_due_parts()
        for turn_id in turn_ids:
            await self._deliverer.deliver_turn(turn_id)
