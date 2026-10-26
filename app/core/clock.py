"""The only place that reads the system clock. Everything else gets a `Clock` injected."""

from datetime import UTC, datetime


class SystemClock:
    """Real time, timezone-aware UTC. Satisfies `app.providers.ports.Clock`."""

    def now(self) -> datetime:
        return datetime.now(UTC)
