"""CuriosityTrajectory: sessions, breadth, slope and rates (s13 §4.5, CLAUDE.md §3)."""

import random
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from app.domain.enums import CuriosityDomain
from app.domain.rules.curiosity_trajectory import CuriosityPoint, CuriosityTrajectory

pytestmark = pytest.mark.unit

START = datetime(2026, 10, 27, 8, 0, tzinfo=UTC)
D = CuriosityDomain


def point(
    hours: float,
    *domains: CuriosityDomain,
    engagement: int = 2,
    asked: bool = False,
) -> CuriosityPoint:
    return CuriosityPoint(
        at=START + timedelta(hours=hours),
        domains=frozenset(domains),
        engagement=engagement,
        child_asked_question=asked,
    )


points_strategy = st.lists(
    st.builds(
        CuriosityPoint,
        at=st.integers(0, 24 * 30).map(lambda hours: START + timedelta(hours=hours)),
        domains=st.frozensets(st.sampled_from(list(CuriosityDomain)), max_size=3),
        engagement=st.integers(0, 3),
        child_asked_question=st.booleans(),
    ),
    max_size=30,
)


def test_exactly_six_hours_apart_is_the_same_session_and_one_minute_more_is_not() -> None:
    times = [START, START + timedelta(hours=6), START + timedelta(hours=12, minutes=1)]
    assert CuriosityTrajectory.split_sessions(times) == [[0, 1], [2]]


def test_sessions_follow_time_not_list_order() -> None:
    times = [START + timedelta(days=2), START]
    assert CuriosityTrajectory.split_sessions(times) == [[1], [0]]


def test_a_child_who_engages_more_each_session_has_a_rising_slope() -> None:
    trajectory = CuriosityTrajectory.of(
        [point(0, D.EARTH_SKY, engagement=1), point(24, D.NATURE_LIVING, engagement=2),
         point(48, D.EARTH_SKY, engagement=3, asked=True)],
        offered=4,
        done=3,
    )  # fmt: skip
    assert trajectory.sessions == 3
    assert trajectory.engagement_by_session == [1, 2, 3]
    assert trajectory.engagement_slope == pytest.approx(1.0)
    assert trajectory.curiosity_breadth == 2
    assert trajectory.done_rate == pytest.approx(0.75)
    assert trajectory.child_question_rate == pytest.approx(1 / 3)
    assert trajectory.returned


def test_one_session_has_no_slope_and_no_return() -> None:
    trajectory = CuriosityTrajectory.of([point(0, D.ART_MUSIC), point(1)], offered=1, done=1)
    assert trajectory.engagement_slope is None
    assert not trajectory.returned
    assert trajectory.engagement_by_session == [2]


def test_nothing_yet_gives_no_rates() -> None:
    trajectory = CuriosityTrajectory.of([], offered=0, done=0)
    assert (trajectory.sessions, trajectory.done_rate, trajectory.child_question_rate) == (
        0,
        None,
        None,
    )


@given(points=points_strategy, extra=points_strategy)
@example(points=[], extra=[point(0, D.EARTH_SKY)])
def test_breadth_never_shrinks_as_history_grows(
    points: list[CuriosityPoint], extra: list[CuriosityPoint]
) -> None:
    assert CuriosityTrajectory.breadth([*points, *extra]) >= CuriosityTrajectory.breadth(points)


@given(points=points_strategy, seed=st.randoms(use_true_random=False))
def test_metrics_dont_depend_on_the_order_points_arrive_in(
    points: list[CuriosityPoint], seed: random.Random
) -> None:
    shuffled = list(points)
    seed.shuffle(shuffled)
    first = CuriosityTrajectory.of(points, offered=5, done=2)
    second = CuriosityTrajectory.of(shuffled, offered=5, done=2)
    assert first == second


@given(values=st.lists(st.integers(0, 3), min_size=2, max_size=20))
def test_a_constant_engagement_has_a_zero_slope_and_adding_a_constant_doesnt_change_it(
    values: list[int],
) -> None:
    assert CuriosityTrajectory.ols_slope([2] * len(values)) == pytest.approx(0.0)
    slope = CuriosityTrajectory.ols_slope(values)
    shifted = CuriosityTrajectory.ols_slope([value + 5 for value in values])
    assert slope is not None
    assert shifted == pytest.approx(slope)
