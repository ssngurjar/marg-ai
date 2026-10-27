"""Rules for turning pending messages into a turn (s04 §4.4, §4.9). Pure.

The store reads rows and the worker acts on them; the decisions in between live here, so they
can be property-tested without a database.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.models import InboundMessage

TURN_RETRY_BASE = timedelta(seconds=5)
TURN_RETRY_CAP = timedelta(seconds=60)
_MAX_DOUBLINGS = 10  # keeps 2^attempts small; the cap applies long before


@dataclass(frozen=True, slots=True)
class QueuedMessage:
    """A pending inbox row: the message, its row id and how many turns have tried it."""

    inbox_id: int
    message: InboundMessage
    attempts: int


def choose_turn_batch(pending: Sequence[QueuedMessage], max_messages: int) -> list[QueuedMessage]:
    """The messages one turn takes: the oldest by when the user sent them, at most `max_messages`.

    Ordering by `provider_sent_at` places a message Meta delivered late where the user sent it;
    the row id breaks ties. Anything past the cap waits for the next turn.
    """
    if max_messages < 1:
        raise ValueError(f"max_messages must be at least 1, got {max_messages}")
    oldest_first = sorted(
        pending, key=lambda queued: (queued.message.provider_sent_at, queued.inbox_id)
    )
    return oldest_first[:max_messages]


def is_poisoned(batch: Sequence[QueuedMessage], max_attempts: int) -> bool:
    """True when a message in the batch has already failed `max_attempts` turns.

    Such a batch isn't run again: the user gets the fixed TRY_AGAIN_LATER reply once.
    """
    return any(queued.attempts >= max_attempts for queued in batch)


def is_stale(batch: Sequence[QueuedMessage], now: datetime, stale_after: timedelta) -> bool:
    """True when every message is older than `stale_after` (Meta's 7-day webhook retries).

    A free-form reply would fail anyway once WhatsApp's 24-hour window has closed.
    """
    if not batch:
        return False
    return all(now - queued.message.provider_sent_at > stale_after for queued in batch)


def turn_retry_delay(attempts: int) -> timedelta:
    """How long a crashed turn's messages wait before the next try: 5 s x 2^attempts, <= 60 s."""
    if attempts < 0:
        raise ValueError(f"attempts can't be negative, got {attempts}")
    return min(TURN_RETRY_BASE * (1 << min(attempts, _MAX_DOUBLINGS)), TURN_RETRY_CAP)
