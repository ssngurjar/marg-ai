"""CircuitBreaker: whether a provider that keeps failing is skipped (s07, owner 2026-11-01).

Two failures in a row within a minute open the breaker: the provider is skipped and its backup
answers at once, instead of waiting out a timeout on every call. While it is open, a probe may
check the provider every half minute; the first success closes it. After `open_for` it closes on
its own and the next call tries the provider again. Pure: the caller passes the time.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class BreakerLimits:
    failures_to_open: int  # BREAKER_FAILURES: failures in a row that open the breaker
    failure_window: timedelta  # BREAKER_WINDOW_S: ...all within this long
    open_for: timedelta  # BREAKER_OPEN_S: how long the provider is skipped at most
    probe_every: timedelta  # BREAKER_PROBE_S: while skipped, how often a probe checks it

    def __post_init__(self) -> None:
        if self.failures_to_open < 1:
            raise ValueError("failures_to_open must be at least 1")
        if min(self.failure_window, self.open_for, self.probe_every) <= timedelta(0):
            raise ValueError("breaker durations must be positive")


@dataclass(frozen=True, slots=True)
class BreakerState:
    """Closed, counting recent failures; or open (skipped) until `open_until`."""

    recent_failures: tuple[datetime, ...] = ()  # while closed: failures in a row, oldest first
    open_until: datetime | None = None
    last_probe_at: datetime | None = None  # while open: when the last probe started


class CircuitBreaker:
    @staticmethod
    def is_open(state: BreakerState, now: datetime) -> bool:
        CircuitBreaker._require_aware(now)
        return state.open_until is not None and now < state.open_until

    @staticmethod
    def after_failure(state: BreakerState, limits: BreakerLimits, now: datetime) -> BreakerState:
        """A failed call. While open (a failed probe) nothing changes: the skip isn't extended."""
        if CircuitBreaker.is_open(state, now):
            return state
        in_window = [
            failed_at
            for failed_at in state.recent_failures
            if now - failed_at < limits.failure_window
        ]
        failures = (*in_window, now)
        if len(failures) >= limits.failures_to_open:
            return BreakerState(open_until=now + limits.open_for, last_probe_at=now)
        return BreakerState(recent_failures=failures)

    @staticmethod
    def after_success() -> BreakerState:
        """A call or probe that worked: closed, with no failures counted."""
        return BreakerState()

    @staticmethod
    def probe_due(state: BreakerState, limits: BreakerLimits, now: datetime) -> bool:
        if not CircuitBreaker.is_open(state, now):
            return False
        return state.last_probe_at is None or now - state.last_probe_at >= limits.probe_every

    @staticmethod
    def probe_started(state: BreakerState, now: datetime) -> BreakerState:
        return replace(state, last_probe_at=now)

    @staticmethod
    def _require_aware(now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("the breaker needs a timezone-aware time")
