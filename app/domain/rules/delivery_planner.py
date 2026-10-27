"""DeliveryPlanner: part order and status changes (s03 §4.8, s04 §4.10). Pure."""

from collections.abc import Sequence
from datetime import timedelta
from typing import ClassVar

from app.domain.enums import OutboxStatus
from app.domain.models.delivery import PartState


class DeliveryPlanner:
    RETRY_BASE: ClassVar[timedelta] = timedelta(seconds=2)
    RETRY_CAP: ClassVar[timedelta] = timedelta(seconds=60)
    _MAX_DOUBLINGS: ClassVar[int] = 10  # keeps 2^attempts small; the cap applies long before
    _FORWARD_ORDER: ClassVar[tuple[OutboxStatus, ...]] = (
        OutboxStatus.PENDING,
        OutboxStatus.SENDING,
        OutboxStatus.SENT,
        OutboxStatus.DELIVERED,
        OutboxStatus.READ,
    )
    _UNFINISHED: ClassVar[frozenset[OutboxStatus]] = frozenset(
        {OutboxStatus.PENDING, OutboxStatus.SENDING}
    )

    @staticmethod
    def next_part_to_send(parts: Sequence[PartState]) -> int | None:
        """The part to send now, or None. Parts go out strictly in `part_no` order.

        The earliest unfinished part is the only candidate: a later part never overtakes a
        pending or sending one. A failed part doesn't block the rest, so text still goes out
        when audio fails.
        """
        for part in sorted(parts, key=lambda state: state.part_no):
            if part.status in DeliveryPlanner._UNFINISHED:
                return part.part_no if part.status is OutboxStatus.PENDING and part.due else None
        return None

    @staticmethod
    def next_status(current: OutboxStatus, reported: OutboxStatus) -> OutboxStatus:
        """The status after Meta reports `reported` for a message currently at `current`.

        Statuses only move forward (sent → delivered → read), so a late "delivered" never
        overwrites "read". "failed" always wins, and nothing moves a failed message forward.
        """
        if reported is OutboxStatus.FAILED or current is OutboxStatus.FAILED:
            return OutboxStatus.FAILED
        order = DeliveryPlanner._FORWARD_ORDER
        if order.index(reported) > order.index(current):
            return reported
        return current

    @staticmethod
    def retry_delay(attempts: int) -> timedelta:
        """How long a retryable send failure waits: 2 s x 2^attempts, at most 60 s."""
        if attempts < 0:
            raise ValueError(f"attempts can't be negative, got {attempts}")
        doublings = 1 << min(attempts, DeliveryPlanner._MAX_DOUBLINGS)
        return min(DeliveryPlanner.RETRY_BASE * doublings, DeliveryPlanner.RETRY_CAP)
