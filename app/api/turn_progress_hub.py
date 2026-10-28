"""TurnProgressHub: routes `turn_progress` notifications to web visitors' open streams (s14 §4.4).

One per api process, fed by its NotificationListener. A notification carries only a turn id;
the hub looks up whose turn it is (cached for the turn's life) and, when that visitor has a
stream open on this process, queues the turn id for each of their streams. Nothing else is
read here: each stream reads its own visitor's turn. A notification for anyone without an open
stream (a WhatsApp user, a visitor on another process) is dropped after the lookup.

After the listener reconnects, every stream is told to look at its latest turn, in case a
notification was missed meanwhile. A stream whose queue fills up (the browser stopped reading)
is closed; the browser reconnects and gets the latest turn replayed.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

from app.core.errors import DemoRefused, StoreError
from app.core.logging import get_logger
from app.domain.models.base import UserHash
from app.store.repositories.demo_repository import DemoRepository

LATEST: Final = None
"""Queued instead of a turn id: look at the latest turn (after a missed notification)."""
OWNER_CACHE_LIMIT: Final = 2000
QUEUE_LIMIT: Final = 100

type QueuedTurn = UUID | None

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class StreamLimits:
    per_visitor: int  # a visitor with two tabs open is fine; a third stream is refused
    per_process: int  # DEMO_SSE_MAX_CONNECTIONS


@dataclass(eq=False, slots=True)
class Subscription:
    """One open stream. `overflowed` is set when its queue filled up and it must close."""

    user_hash: UserHash
    queue: asyncio.Queue[QueuedTurn] = field(
        default_factory=lambda: asyncio.Queue(maxsize=QUEUE_LIMIT)
    )
    overflowed: bool = False


class TurnProgressHub:
    def __init__(self, demo: DemoRepository, limits: StreamLimits) -> None:
        self._demo = demo
        self._limits = limits
        self._streams: dict[UserHash, set[Subscription]] = {}
        self._owners: dict[UUID, UserHash] = {}
        self._lookups: set[asyncio.Task[None]] = set()

    @property
    def open_streams(self) -> int:
        return sum(len(streams) for streams in self._streams.values())

    def open(self, user_hash: UserHash) -> Subscription:
        """Raises DemoRefused (`stream_limit`) past either limit."""
        mine = self._streams.get(user_hash, set())
        if len(mine) >= self._limits.per_visitor or self.open_streams >= self._limits.per_process:
            raise DemoRefused("stream_limit", scope="streams")
        subscription = Subscription(user_hash)
        self._streams.setdefault(user_hash, set()).add(subscription)
        return subscription

    def close(self, subscription: Subscription) -> None:
        mine = self._streams.get(subscription.user_hash)
        if mine is None:
            return
        mine.discard(subscription)
        if not mine:
            del self._streams[subscription.user_hash]

    def on_notification(self, payload: str) -> None:
        """The listener's handler: "" after a (re)connect, otherwise a turn id."""
        if not self._streams:
            return  # nobody is watching: no lookup needed
        if not payload:
            for streams in self._streams.values():
                for subscription in streams:
                    _offer(subscription, LATEST)
            return
        try:
            turn_id = UUID(payload)
        except ValueError:
            logger.warning("turn_progress_bad_payload")
            return
        owner = self._owners.get(turn_id)
        if owner is not None:
            self._deliver(owner, turn_id)
            return
        lookup = asyncio.create_task(self._look_up_and_deliver(turn_id), name="turn-owner")
        self._lookups.add(lookup)
        lookup.add_done_callback(self._lookups.discard)

    async def _look_up_and_deliver(self, turn_id: UUID) -> None:
        try:
            owner = await self._demo.turn_owner(turn_id)
        except StoreError as exc:  # the stream misses one update; the next one catches up
            logger.warning("turn_owner_lookup_failed", exc_info=exc)
            return
        if owner is None:
            return
        if len(self._owners) >= OWNER_CACHE_LIMIT:
            self._owners.clear()
        self._owners[turn_id] = owner
        self._deliver(owner, turn_id)

    def _deliver(self, owner: UserHash, turn_id: UUID) -> None:
        for subscription in self._streams.get(owner, set()):
            _offer(subscription, turn_id)


def _offer(subscription: Subscription, item: QueuedTurn) -> None:
    try:
        subscription.queue.put_nowait(item)
    except asyncio.QueueFull:
        subscription.overflowed = True
