"""A clock tests control."""

from datetime import datetime, timedelta


class FixedClock:
    """Satisfies `app.providers.ports.Clock`; time moves only when a test advances it."""

    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FixedClock needs a timezone-aware datetime")
        self._now = at

    def now(self) -> datetime:
        return self._now

    def advance(self, by: timedelta) -> None:
        self._now += by
