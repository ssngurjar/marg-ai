"""Where an outbound part stands in its delivery (s04 §4.10)."""

from dataclasses import dataclass

from app.domain.enums import OutboxStatus


@dataclass(frozen=True, slots=True)
class PartState:
    """One outbound part of a turn: its number, status, and whether its retry time has come."""

    part_no: int
    status: OutboxStatus
    due: bool
