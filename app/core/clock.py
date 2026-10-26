"""Time. The only place that reads the system clock; everything else gets a `Clock` injected."""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Source of the current time: aware UTC."""

    def now(self) -> datetime: ...


class SystemClock:
    """Real time, timezone-aware UTC."""

    def now(self) -> datetime:
        return datetime.now(UTC)
