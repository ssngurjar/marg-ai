"""Aspiration signals and the student trajectory (s13 §4.3, §4.5; CLAUDE.md §3 properties)."""

import random
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.enums import AspirationField, ConstraintKind, Sentiment
from app.domain.models.aspiration import AspirationSignals
from app.domain.rules.aspiration_trajectory import AspirationPoint, AspirationTrajectory

pytestmark = pytest.mark.unit

START = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
F = AspirationField


def signals(**change: object) -> dict[str, object]:
    return {
        "fields": ["medicine"],
        "specificity": 3,
        "constraints": ["money"],
        "sentiment": "positive",
        **change,
    }


def test_a_consistent_answer_validates() -> None:
    parsed = AspirationSignals.model_validate(signals())
    assert parsed.fields == [F.MEDICINE]
    assert parsed.sentiment is Sentiment.POSITIVE


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"specificity": 0}, "specificity 0 has no fields"),
        ({"specificity": 2, "fields": []}, "names at least one field"),
        ({"fields": ["sports", "sports"]}, "must not repeat"),
        ({"constraints": ["money", "money"]}, "must not repeat"),
        ({"specificity": 5}, "less than or equal to 4"),
        ({"fields": ["astrology"]}, "fields"),
        ({"fields": ["sports", "law", "teaching", "agriculture"]}, "at most 3"),
    ],
)
def test_inconsistent_answers_are_refused(change: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        AspirationSignals.model_validate(signals(**change))


def test_specificity_one_may_name_no_field() -> None:
    assert AspirationSignals.model_validate(signals(specificity=1, fields=[])).fields == []


points = st.builds(
    AspirationPoint,
    at=st.integers(0, 24 * 30).map(lambda hours: START + timedelta(hours=hours)),
    fields=st.frozensets(st.sampled_from(list(AspirationField)), max_size=3),
    specificity=st.integers(0, 4),
    constraints=st.frozensets(st.sampled_from(list(ConstraintKind)), max_size=3),
)


@given(st.lists(points, max_size=25))
def test_breadth_never_shrinks_as_history_grows_and_ignores_other(
    history: list[AspirationPoint],
) -> None:
    previous = 0
    for size in range(len(history) + 1):
        current = AspirationTrajectory.breadth(history[:size])
        assert current >= previous
        previous = current
    assert previous <= len(AspirationField) - 1


@given(st.lists(points, max_size=25))
def test_the_trajectory_is_bounded(history: list[AspirationPoint]) -> None:
    trajectory = AspirationTrajectory.of(history)
    assert all(0 <= level <= 4 for level in trajectory.specificity_by_session)
    if trajectory.specificity_slope is not None:
        assert abs(trajectory.specificity_slope) <= 4
    assert trajectory.returned is (trajectory.sessions >= 2)


@given(st.lists(points, min_size=1, max_size=25), st.randoms(use_true_random=False))
def test_the_order_points_arrive_in_never_changes_the_trajectory(
    history: list[AspirationPoint], shuffler: random.Random
) -> None:
    shuffled = list(history)
    shuffler.shuffle(shuffled)
    assert AspirationTrajectory.of(shuffled) == AspirationTrajectory.of(history)


def test_a_known_series_has_the_known_slope() -> None:
    history = [
        AspirationPoint(START + timedelta(days=day), frozenset({F.SPORTS}), level, frozenset())
        for day, level in enumerate([1, 2, 3, 4])
    ]
    assert AspirationTrajectory.of(history).specificity_slope == 1.0
