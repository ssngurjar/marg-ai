"""CircuitBreaker: when a failing provider is skipped, and when it's tried again (s07, owner
2026-11-01)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.circuit_breaker import BreakerLimits, BreakerState, CircuitBreaker

pytestmark = pytest.mark.unit

START = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
LIMITS = BreakerLimits(
    failures_to_open=2,
    failure_window=timedelta(seconds=60),
    open_for=timedelta(minutes=5),
    probe_every=timedelta(seconds=30),
)


def failures_at(*seconds: float, limits: BreakerLimits = LIMITS) -> BreakerState:
    state = BreakerState()
    for second in seconds:
        state = CircuitBreaker.after_failure(state, limits, START + timedelta(seconds=second))
    return state


# --- examples ------------------------------------------------------------------------------------


def test_a_new_breaker_is_closed_and_needs_no_probe() -> None:
    assert not CircuitBreaker.is_open(BreakerState(), START)
    assert not CircuitBreaker.probe_due(BreakerState(), LIMITS, START)


def test_one_failure_does_not_open_it() -> None:
    assert not CircuitBreaker.is_open(failures_at(0), START)


def test_two_failures_within_a_minute_open_it_for_five_minutes() -> None:
    state = failures_at(0, 59)
    opened_at = START + timedelta(seconds=59)
    assert CircuitBreaker.is_open(state, opened_at)
    assert CircuitBreaker.is_open(state, opened_at + timedelta(minutes=5) - timedelta(seconds=1))
    assert not CircuitBreaker.is_open(state, opened_at + timedelta(minutes=5))


def test_two_failures_a_minute_or_more_apart_do_not_open_it() -> None:
    assert not CircuitBreaker.is_open(failures_at(0, 60), START + timedelta(seconds=60))


def test_a_success_between_failures_starts_the_count_again() -> None:
    ten_seconds_in = START + timedelta(seconds=10)
    without_success = CircuitBreaker.after_failure(failures_at(0), LIMITS, ten_seconds_in)
    after_success = CircuitBreaker.after_failure(
        CircuitBreaker.after_success(), LIMITS, ten_seconds_in
    )
    assert CircuitBreaker.is_open(without_success, ten_seconds_in)
    assert not CircuitBreaker.is_open(after_success, ten_seconds_in)


def test_the_first_probe_is_due_half_a_minute_after_opening() -> None:
    state = failures_at(0, 1)
    opened_at = START + timedelta(seconds=1)
    assert not CircuitBreaker.probe_due(state, LIMITS, opened_at + timedelta(seconds=29))
    assert CircuitBreaker.probe_due(state, LIMITS, opened_at + timedelta(seconds=30))


def test_a_started_probe_makes_the_next_one_wait_half_a_minute() -> None:
    probe_at = START + timedelta(seconds=31)
    state = CircuitBreaker.probe_started(failures_at(0, 1), probe_at)
    assert not CircuitBreaker.probe_due(state, LIMITS, probe_at + timedelta(seconds=29))
    assert CircuitBreaker.probe_due(state, LIMITS, probe_at + timedelta(seconds=30))


def test_a_failed_probe_does_not_extend_the_skip() -> None:
    state = failures_at(0, 1)
    after_probe = CircuitBreaker.after_failure(state, LIMITS, START + timedelta(seconds=31))
    assert after_probe == state


def test_a_successful_probe_closes_it() -> None:
    assert not CircuitBreaker.is_open(CircuitBreaker.after_success(), START)


def test_a_naive_time_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        CircuitBreaker.is_open(BreakerState(), datetime(2026, 11, 1, 8, 0))  # noqa: DTZ001  # the naive time under test


@pytest.mark.parametrize(
    ("failures", "window", "open_for", "probe_every", "message"),
    [
        (0, 60, 300, 30, "failures_to_open must be at least 1"),
        (2, 0, 300, 30, "durations must be positive"),
        (2, 60, -1, 30, "durations must be positive"),
        (2, 60, 300, 0, "durations must be positive"),
    ],
)
def test_impossible_limits_are_refused(
    failures: int, window: float, open_for: float, probe_every: float, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        BreakerLimits(
            failures_to_open=failures,
            failure_window=timedelta(seconds=window),
            open_for=timedelta(seconds=open_for),
            probe_every=timedelta(seconds=probe_every),
        )


# --- properties ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Event:
    kind: Literal["failure", "success", "probe"]
    after_s: float  # seconds after the previous event


events = st.lists(
    st.builds(
        Event,
        kind=st.sampled_from(["failure", "success", "probe"]),
        after_s=st.floats(min_value=0, max_value=400, allow_nan=False),
    ),
    max_size=40,
)
limits_strategy = st.builds(
    BreakerLimits,
    failures_to_open=st.integers(min_value=1, max_value=4),
    failure_window=st.integers(min_value=1, max_value=120).map(lambda s: timedelta(seconds=s)),
    open_for=st.integers(min_value=1, max_value=600).map(lambda s: timedelta(seconds=s)),
    probe_every=st.integers(min_value=1, max_value=60).map(lambda s: timedelta(seconds=s)),
)


@dataclass(frozen=True, slots=True)
class Step:
    at: datetime
    before: BreakerState
    after: BreakerState
    event: Event


def replay(history: list[Event], limits: BreakerLimits) -> list[Step]:
    steps: list[Step] = []
    state, now = BreakerState(), START
    for event in history:
        now += timedelta(seconds=event.after_s)
        if event.kind == "failure":
            changed = CircuitBreaker.after_failure(state, limits, now)
        elif event.kind == "success":
            changed = CircuitBreaker.after_success()
        else:
            due = CircuitBreaker.probe_due(state, limits, now)
            changed = CircuitBreaker.probe_started(state, now) if due else state
        steps.append(Step(now, state, changed, event))
        state = changed
    return steps


@given(events, limits_strategy)
def test_it_opens_only_on_enough_failures_in_a_row_within_the_window(
    history: list[Event], limits: BreakerLimits
) -> None:
    failures_in_a_row: list[datetime] = []
    for step in replay(history, limits):
        if step.event.kind == "success":
            failures_in_a_row = []
        if step.event.kind != "failure" or CircuitBreaker.is_open(step.before, step.at):
            continue
        failures_in_a_row.append(step.at)
        recent = [at for at in failures_in_a_row if step.at - at < limits.failure_window]
        opened = CircuitBreaker.is_open(step.after, step.at)
        assert opened == (len(recent) >= limits.failures_to_open)
        if opened:
            failures_in_a_row = []


@given(events, limits_strategy)
def test_it_is_never_skipped_longer_than_open_for(
    history: list[Event], limits: BreakerLimits
) -> None:
    for step in replay(history, limits):
        if step.after.open_until is not None:
            assert step.after.open_until - step.at <= limits.open_for
            assert not CircuitBreaker.is_open(step.after, step.after.open_until)


@given(events, limits_strategy)
def test_a_success_always_closes_it(history: list[Event], limits: BreakerLimits) -> None:
    for step in replay(history, limits):
        if step.event.kind == "success":
            assert not CircuitBreaker.is_open(step.after, step.at)
            assert step.after.recent_failures == ()


@given(events, limits_strategy)
def test_probes_happen_only_while_open_and_at_most_once_per_interval(
    history: list[Event], limits: BreakerLimits
) -> None:
    last_probe: datetime | None = None
    for step in replay(history, limits):
        if step.event.kind != "probe" or step.after == step.before:
            continue
        assert CircuitBreaker.is_open(step.before, step.at)
        if last_probe is not None and step.before.open_until == step.after.open_until:
            assert step.at - last_probe >= limits.probe_every
        last_probe = step.at
