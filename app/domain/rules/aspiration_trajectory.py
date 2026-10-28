"""AspirationTrajectory: how a student's aim sharpens over sessions (s13 §4.5). Pure.

The same session and slope definitions as CuriosityTrajectory (a session ends after a gap of
more than 6 hours; least-squares slope over the session index, from two sessions on), so a
child's curiosity and the student they become are measured on one axis. Breadth counts the
distinct fields explored, OTHER excluded; the per-session value is the highest specificity.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.domain.enums import AspirationField, ConstraintKind
from app.domain.rules.curiosity_trajectory import CuriosityTrajectory


@dataclass(frozen=True, slots=True)
class AspirationPoint:
    at: datetime  # when the turn started
    fields: frozenset[AspirationField]
    specificity: int  # 0..4
    constraints: frozenset[ConstraintKind]


@dataclass(frozen=True, slots=True)
class StudentTrajectory:
    sessions: int
    breadth: int  # distinct fields explored, OTHER excluded
    specificity_by_session: list[int]  # the highest specificity per session, oldest first
    specificity_slope: float | None  # None with fewer than 2 sessions
    returned: bool  # came back for a second session


class AspirationTrajectory:
    @staticmethod
    def breadth(points: Sequence[AspirationPoint]) -> int:
        fields: set[AspirationField] = set()
        for point in points:
            fields.update(point.fields)
        fields.discard(AspirationField.OTHER)
        return len(fields)

    @staticmethod
    def of(points: Sequence[AspirationPoint]) -> StudentTrajectory:
        sessions = CuriosityTrajectory.split_sessions([point.at for point in points])
        by_session = [max(points[index].specificity for index in session) for session in sessions]
        return StudentTrajectory(
            sessions=len(sessions),
            breadth=AspirationTrajectory.breadth(points),
            specificity_by_session=by_session,
            specificity_slope=CuriosityTrajectory.ols_slope(by_session),
            returned=len(sessions) >= CuriosityTrajectory.TWO_SESSIONS,
        )
