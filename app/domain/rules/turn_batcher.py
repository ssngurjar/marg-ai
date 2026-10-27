"""TurnBatcher: which pending messages a turn takes, and when it gives up (s04 §4.4, §4.9). Pure.

The store reads rows and the worker acts on them; the decisions in between live here, so they
can be property-tested without a database.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import ClassVar

from app.domain.models.turn import QueuedMessage


class TurnBatcher:
    RETRY_BASE: ClassVar[timedelta] = timedelta(seconds=5)
    RETRY_CAP: ClassVar[timedelta] = timedelta(seconds=60)
    _MAX_DOUBLINGS: ClassVar[int] = 10  # keeps 2^attempts small; the cap applies long before

    @staticmethod
    def choose_batch(pending: Sequence[QueuedMessage], max_messages: int) -> list[QueuedMessage]:
        """The messages one turn takes: the oldest by when the user sent them, at most
        `max_messages`.

        Ordering by `provider_sent_at` places a message Meta delivered late where the user sent
        it; the row id breaks ties. Anything past the cap waits for the next turn.
        """
        if max_messages < 1:
            raise ValueError(f"max_messages must be at least 1, got {max_messages}")
        oldest_first = sorted(
            pending, key=lambda queued: (queued.message.provider_sent_at, queued.inbox_id)
        )
        return oldest_first[:max_messages]

    @staticmethod
    def is_poisoned(batch: Sequence[QueuedMessage], max_attempts: int) -> bool:
        """True when a message in the batch has already failed `max_attempts` turns.

        Such a batch isn't run again: the user gets the fixed TRY_AGAIN_LATER reply once.
        """
        return any(queued.attempts >= max_attempts for queued in batch)

    @staticmethod
    def is_stale(batch: Sequence[QueuedMessage], now: datetime, stale_after: timedelta) -> bool:
        """True when every message is older than `stale_after` (Meta's 7-day webhook retries).

        A free-form reply would fail anyway once WhatsApp's 24-hour window has closed.
        """
        if not batch:
            return False
        return all(now - queued.message.provider_sent_at > stale_after for queued in batch)

    @staticmethod
    def retry_delay(attempts: int) -> timedelta:
        """How long a crashed turn's messages wait before the next try: 5 s x 2^attempts,
        at most 60 s."""
        if attempts < 0:
            raise ValueError(f"attempts can't be negative, got {attempts}")
        doublings = 1 << min(attempts, TurnBatcher._MAX_DOUBLINGS)
        return min(TurnBatcher.RETRY_BASE * doublings, TurnBatcher.RETRY_CAP)
