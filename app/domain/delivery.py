"""Outbound delivery rules (s03 §4.8, s04 §4.10). Pure; used by the outbox store and the worker."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from app.domain.enums import OutboxStatus

_FORWARD_ORDER = (
    OutboxStatus.PENDING,
    OutboxStatus.SENDING,
    OutboxStatus.SENT,
    OutboxStatus.DELIVERED,
    OutboxStatus.READ,
)


def next_delivery_status(current: OutboxStatus, reported: OutboxStatus) -> OutboxStatus:
    """The status after Meta reports `reported` for a message currently at `current`.

    Statuses only move forward (sent → delivered → read), so a late "delivered" never
    overwrites "read". "failed" always wins, and nothing moves a failed message forward again.
    """
    if reported is OutboxStatus.FAILED or current is OutboxStatus.FAILED:
        return OutboxStatus.FAILED
    if _FORWARD_ORDER.index(reported) > _FORWARD_ORDER.index(current):
        return reported
    return current


OUTBOX_RETRY_BASE = timedelta(seconds=2)
OUTBOX_RETRY_CAP = timedelta(seconds=60)
_MAX_DOUBLINGS = 10  # keeps 2^attempts small; the cap applies long before
_UNFINISHED = frozenset({OutboxStatus.PENDING, OutboxStatus.SENDING})


@dataclass(frozen=True, slots=True)
class PartState:
    """Where one outbound part of a turn stands."""

    part_no: int
    status: OutboxStatus
    due: bool  # its retry time has come


def next_part_to_send(parts: Sequence[PartState]) -> int | None:
    """The part to send now, or None. Parts go out strictly in `part_no` order (s04 §4.10).

    The earliest unfinished part is the only candidate: a later part never overtakes a pending
    or sending one. A failed part doesn't block the rest, so text still goes out when audio fails.
    """
    for part in sorted(parts, key=lambda state: state.part_no):
        if part.status in _UNFINISHED:
            return part.part_no if part.status is OutboxStatus.PENDING and part.due else None
    return None


def outbox_retry_delay(attempts: int) -> timedelta:
    """How long a retryable send failure waits: 2 s x 2^attempts, at most 60 s."""
    if attempts < 0:
        raise ValueError(f"attempts can't be negative, got {attempts}")
    return min(OUTBOX_RETRY_BASE * (1 << min(attempts, _MAX_DOUBLINGS)), OUTBOX_RETRY_CAP)
