"""StudentDashboardBuilder: students' aims over time, behind the k-anonymity floor (s13 §4.7)."""

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.domain.enums import AspirationField, ConstraintKind
from app.domain.models.learner import LearnerId
from app.domain.rules.aspiration_trajectory import AspirationPoint
from app.store.repositories.telemetry_repository import StudentData
from app.telemetry.student_dashboard_builder import StudentDashboard, StudentDashboardBuilder
from tests.fakes.clock import FixedClock
from tests.fakes.telemetry_reader import FakeTelemetryReader

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
F, C = AspirationField, ConstraintKind


def point(
    days_ago: float,
    level: int,
    fields: set[AspirationField],
    constraints: frozenset[ConstraintKind] = frozenset(),
) -> AspirationPoint:
    return AspirationPoint(NOW - timedelta(days=days_ago), frozenset(fields), level, constraints)


def cohort(students: int) -> StudentData:
    data = StudentData(roadmaps_created=6, turns_by_route={"mentor": 20, "roadmap": 6})
    for number in range(1, students + 1):
        data.points[LearnerId(UUID(int=number))] = [
            point(3, 1, set()),
            point(1, 3, {F.MEDICINE}, frozenset({C.MONEY})),
        ]
    return data


async def build(data: StudentData, floor: int = 5) -> StudentDashboard:
    return await StudentDashboardBuilder(FakeTelemetryReader(student=data), FixedClock(NOW)).build(
        floor
    )


async def test_fewer_students_than_the_floor_shows_only_the_notice() -> None:
    board = await build(cohort(4))
    assert board.enough is False
    assert (board.students, board.fields, board.weeks) == (None, [], [])


async def test_the_headline_shows_return_breadth_and_aims_sharpening() -> None:
    board = await build(cohort(5))
    assert (board.students, board.sessions) == (5, 10)
    assert board.return_rate == 1.0
    assert board.median_breadth == 1
    assert board.median_slope == 2.0  # specificity 1 → 3 over two sessions
    assert board.roadmaps_created == 6


async def test_fields_and_constraints_count_students_and_hide_small_cells() -> None:
    data = cohort(5)
    data.points[LearnerId(UUID(int=1))].append(point(0.5, 3, {F.SPORTS}))
    board = await build(data)
    fields = {bucket.label: bucket.children for bucket in board.fields}
    assert fields["medicine"] == 5
    assert fields["sports"] is None  # one student: hidden
    assert "other" not in fields
    constraints = {bucket.label: bucket.children for bucket in board.constraints}
    assert constraints["money"] == 5


async def test_a_week_with_too_few_students_is_left_out() -> None:
    data = cohort(5)
    data.points[LearnerId(UUID(int=1))].append(point(20, 2, {F.LAW}))
    weeks = [week.week for week in (await build(data)).weeks]
    assert "2026-W41" not in weeks
    assert weeks == sorted(weeks)


async def test_nothing_identifying_leaves_the_builder() -> None:
    dumped = (await build(cohort(6), floor=1)).model_dump_json()
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", dumped)
