"""StudentDashboardBuilder: the students section of /dashboard (s13 §4.5, §4.7).

The continuation of the young learners' section: a child's curiosity domains become a student's
aspiration fields, measured with the same sessions and slope. Headline numbers, how many fields
each student explores, which fields, what holds them back (the actionable part for a teacher),
how sharp their aims get per ISO week, plans made and how turns were routed. The k-anonymity
floor applies to every number drawn from students. Counts only, never a learner or a word.
"""

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from statistics import median
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from app.core.clock import Clock
from app.domain.enums import AspirationField, ConstraintKind
from app.domain.models.learner import LearnerId
from app.domain.rules.aspiration_trajectory import (
    AspirationPoint,
    AspirationTrajectory,
    StudentTrajectory,
)
from app.telemetry.dashboard_builder import Bucket
from app.telemetry.small_count_suppressor import SmallCountSuppressor
from app.telemetry.telemetry_reader import TelemetryReader


class WeekSpecificity(BaseModel):
    """One ISO week's student turns: the share at each specificity level 0-4."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    week: str
    turns: int
    level_shares: list[float]  # five shares, levels 0..4, summing to 1


class RouteCount(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    route: str
    turns: int


class StudentDashboard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime
    floor: int
    enough: bool  # False: "Not enough students yet", and every section below is empty
    students: int | None
    sessions: int | None
    return_rate: float | None
    median_breadth: float | None
    median_slope: float | None  # levels of specificity gained per session
    breadth: list[Bucket]
    fields: list[Bucket]
    constraints: list[Bucket]
    weeks: list[WeekSpecificity]
    roadmaps_created: int | None
    turns_by_route: list[RouteCount]


class StudentDashboardBuilder:
    RETURN_WINDOW: ClassVar[timedelta] = timedelta(hours=24)
    BREADTH_LABELS: ClassVar[tuple[str, ...]] = ("0", "1", "2", "3", "4+")
    LEVELS: ClassVar[int] = 5  # specificity 0..4

    def __init__(self, reader: TelemetryReader, clock: Clock) -> None:
        self._reader = reader
        self._clock = clock

    async def build(self, floor: int, district: str | None = None) -> StudentDashboard:
        """All students, or one district's (a teacher's view). Raises StoreError when the
        database can't be read."""
        data = await self._reader.students(district)
        now = self._clock.now()
        if len(data.points) < floor:
            return _not_enough(now, floor)
        trajectories: dict[LearnerId, StudentTrajectory] = {}
        for learner_id, points in data.points.items():
            trajectories[learner_id] = AspirationTrajectory.of(points)
        slopes: list[float] = []
        for trajectory in trajectories.values():
            if trajectory.specificity_slope is not None:
                slopes.append(trajectory.specificity_slope)
        explored_fields = [field for field in AspirationField if field is not AspirationField.OTHER]
        return StudentDashboard(
            generated_at=now,
            floor=floor,
            enough=True,
            students=len(data.points),
            sessions=sum(trajectory.sessions for trajectory in trajectories.values()),
            return_rate=self._return_rate(data.points, trajectories, now, floor),
            median_breadth=median(trajectory.breadth for trajectory in trajectories.values()),
            median_slope=median(slopes) if len(slopes) >= floor else None,
            breadth=self._breadth(list(trajectories.values()), floor),
            fields=_students_per(
                data.points, [field.value for field in explored_fields], _field_values, floor
            ),
            constraints=_students_per(
                data.points,
                [constraint.value for constraint in ConstraintKind],
                _constraint_values,
                floor,
            ),
            weeks=self._weeks(data.points, floor),
            roadmaps_created=SmallCountSuppressor.count(data.roadmaps_created, floor),
            turns_by_route=[
                RouteCount(route=route, turns=turns)
                for route, turns in sorted(data.turns_by_route.items())
            ],
        )

    def _return_rate(
        self,
        points: Mapping[LearnerId, Sequence[AspirationPoint]],
        trajectories: Mapping[LearnerId, StudentTrajectory],
        now: datetime,
        floor: int,
    ) -> float | None:
        """Students who came back ÷ students whose first turn is over 24 hours old."""
        eligible: list[LearnerId] = []
        for learner_id, student_points in points.items():
            if min(point.at for point in student_points) <= now - self.RETURN_WINDOW:
                eligible.append(learner_id)
        if SmallCountSuppressor.count(len(eligible), floor) is None:
            return None
        returned = sum(1 for learner_id in eligible if trajectories[learner_id].returned)
        return returned / len(eligible)

    def _breadth(self, trajectories: Sequence[StudentTrajectory], floor: int) -> list[Bucket]:
        last = len(self.BREADTH_LABELS) - 1
        students_per_label = dict.fromkeys(self.BREADTH_LABELS, 0)
        for trajectory in trajectories:
            students_per_label[self.BREADTH_LABELS[min(trajectory.breadth, last)]] += 1
        shown = SmallCountSuppressor.counts(students_per_label, floor)
        return [Bucket(label=label, children=count) for label, count in shown.items()]

    def _weeks(
        self, points: Mapping[LearnerId, Sequence[AspirationPoint]], floor: int
    ) -> list[WeekSpecificity]:
        """Per ISO week, oldest first; a week with fewer than `floor` students is left out."""
        levels_by_week: defaultdict[str, list[int]] = defaultdict(list)
        students_by_week: defaultdict[str, set[LearnerId]] = defaultdict(set)
        for learner_id, student_points in points.items():
            for point in student_points:
                year, week, _ = point.at.isocalendar()
                label = f"{year}-W{week:02d}"
                levels_by_week[label].append(point.specificity)
                students_by_week[label].add(learner_id)
        weeks: list[WeekSpecificity] = []
        for label in sorted(levels_by_week):
            if SmallCountSuppressor.count(len(students_by_week[label]), floor) is None:
                continue  # too few students that week to show anything about it
            levels = levels_by_week[label]
            counts = [0] * self.LEVELS
            for level in levels:
                counts[level] += 1
            weeks.append(
                WeekSpecificity(
                    week=label,
                    turns=len(levels),
                    level_shares=[count / len(levels) for count in counts],
                )
            )
        return weeks


def _field_values(point: AspirationPoint) -> frozenset[str]:
    return frozenset(field.value for field in point.fields)


def _constraint_values(point: AspirationPoint) -> frozenset[str]:
    return frozenset(constraint.value for constraint in point.constraints)


def _students_per(
    points: Mapping[LearnerId, Sequence[AspirationPoint]],
    vocabulary: Sequence[str],
    values_of: Callable[[AspirationPoint], frozenset[str]],
    floor: int,
) -> list[Bucket]:
    """How many students ever named each value, hidden below the floor."""
    students_per_value = dict.fromkeys(vocabulary, 0)
    for student_points in points.values():
        named: set[str] = set()
        for point in student_points:
            named.update(values_of(point))
        for value in named & set(vocabulary):
            students_per_value[value] += 1
    shown = SmallCountSuppressor.counts(students_per_value, floor)
    return [Bucket(label=label, children=count) for label, count in shown.items()]


def _not_enough(now: datetime, floor: int) -> StudentDashboard:
    return StudentDashboard(
        generated_at=now,
        floor=floor,
        enough=False,
        students=None,
        sessions=None,
        return_rate=None,
        median_breadth=None,
        median_slope=None,
        breadth=[],
        fields=[],
        constraints=[],
        weeks=[],
        roadmaps_created=None,
        turns_by_route=[],
    )
