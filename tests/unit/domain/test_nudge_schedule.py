"""NudgeSchedule: the daily khoj message's time, in India (s10b §4.11)."""

from datetime import UTC, datetime, time, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.rules.nudge_schedule import NudgeSchedule

pytestmark = pytest.mark.unit

IST = NudgeSchedule.INDIA


def ist(hour: int, minute: int = 0, day: int = 27) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=IST).astimezone(UTC)


def test_before_the_time_today_it_is_due_today() -> None:
    assert NudgeSchedule.next_due(time(8, 0), ist(6, 30)) == ist(8)


def test_after_the_time_it_is_due_tomorrow() -> None:
    assert NudgeSchedule.next_due(time(8, 0), ist(9)) == ist(8, day=28)


def test_exactly_at_the_time_it_is_due_tomorrow_not_again_now() -> None:
    assert NudgeSchedule.next_due(time(18, 0), ist(18)) == ist(18, day=28)


def test_the_india_day_not_the_utc_day_decides() -> None:
    """23:30 UTC on the 27th is already 05:00 IST on the 28th."""
    late_utc = datetime(2026, 10, 27, 23, 30, tzinfo=UTC)
    assert NudgeSchedule.next_due(time(8, 0), late_utc) == ist(8, day=28)


def test_a_naive_time_is_refused() -> None:
    with pytest.raises(ValueError, match="aware datetime"):
        NudgeSchedule.next_due(time(8, 0), datetime(2026, 10, 27, 8, 0))  # noqa: DTZ001  # the naive input under test


@pytest.mark.parametrize(("hour", "minute"), [(20, 0), (23, 59), (0, 0), (6, 59)])
def test_quiet_hours_are_20_00_to_07_00_in_india(hour: int, minute: int) -> None:
    assert NudgeSchedule.in_quiet_hours(ist(hour, minute))


@pytest.mark.parametrize(("hour", "minute"), [(7, 0), (8, 0), (18, 0), (19, 59)])
def test_the_day_is_not_quiet(hour: int, minute: int) -> None:
    assert not NudgeSchedule.in_quiet_hours(ist(hour, minute))


def test_the_india_day_starts_at_midnight_ist() -> None:
    assert NudgeSchedule.start_of_india_day(ist(15)) == ist(0)


@given(
    minutes_into_day=st.integers(0, 24 * 60 - 1),
    hour=st.integers(0, 23),
    minute=st.sampled_from([0, 30]),
)
def test_the_next_time_is_after_now_within_a_day_and_at_the_chosen_time(
    minutes_into_day: int, hour: int, minute: int
) -> None:
    now = ist(0) + timedelta(minutes=minutes_into_day)
    due = NudgeSchedule.next_due(time(hour, minute), now)
    assert now < due <= now + timedelta(days=1)
    assert due.astimezone(IST).time() == time(hour, minute)
