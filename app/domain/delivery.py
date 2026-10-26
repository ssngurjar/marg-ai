"""How a sent message's delivery status may change (s03 §4.8). Pure; used by the outbox store."""

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
