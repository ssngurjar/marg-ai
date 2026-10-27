"""CuriosityTrajectory: how a young child's curiosity grows over sessions (s13 §4.5). Pure.

Inputs are plain records, so the math is property-tested without a database. Exact
definitions (s13): a new session starts after a gap of more than 6 hours (SessionRules); the
per-session value is the highest engagement in it; the slope is ordinary least squares over the
session index, defined from two sessions on.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from app.domain.enums import CuriosityDomain
from app.domain.rules.session_rules import SessionRules


@dataclass(frozen=True, slots=True)
class CuriosityPoint:
    at: datetime  # when the turn started
    domains: frozenset[CuriosityDomain]
    engagement: int  # 0..3
    child_asked_question: bool


@dataclass(frozen=True, slots=True)
class YoungLearnerTrajectory:
    sessions: int
    activities_offered: int
    activities_done: int
    done_rate: float | None  # None when nothing was offered
    curiosity_breadth: int  # distinct domains across all points
    engagement_by_session: list[int]  # the highest engagement per session, oldest first
    engagement_slope: float | None  # None with fewer than 2 sessions
    child_question_rate: float | None  # points where the child asked ÷ points; None when none
    returned: bool  # came back for a second session


class CuriosityTrajectory:
    TWO_SESSIONS: ClassVar[int] = 2  # a slope needs two sessions; a second session is a return

    @staticmethod
    def split_sessions(times: Sequence[datetime]) -> list[list[int]]:
        """Indices of `times` grouped into sessions, in time order (a stable sort keeps equal
        times in their given order)."""
        order = sorted(range(len(times)), key=lambda index: times[index])
        sessions: list[list[int]] = []
        previous: datetime | None = None
        for index in order:
            current = times[index]
            if previous is None or current - previous > SessionRules.SESSION_GAP:
                sessions.append([])
            sessions[-1].append(index)
            previous = current
        return sessions

    @staticmethod
    def breadth(points: Sequence[CuriosityPoint]) -> int:
        domains: set[CuriosityDomain] = set()
        for point in points:
            domains.update(point.domains)
        return len(domains)

    @staticmethod
    def ols_slope(per_session: Sequence[int]) -> float | None:
        """Least-squares slope of the values against 0..n-1 (levels per session)."""
        count = len(per_session)
        if count < CuriosityTrajectory.TWO_SESSIONS:
            return None
        mean_index = (count - 1) / 2
        mean_value = sum(per_session) / count
        covariance = sum(
            (index - mean_index) * (value - mean_value) for index, value in enumerate(per_session)
        )
        variance = sum((index - mean_index) ** 2 for index in range(count))
        return covariance / variance

    @staticmethod
    def of(points: Sequence[CuriosityPoint], offered: int, done: int) -> YoungLearnerTrajectory:
        sessions = CuriosityTrajectory.split_sessions([point.at for point in points])
        engagement_by_session = [
            max(points[index].engagement for index in session) for session in sessions
        ]
        asked = sum(1 for point in points if point.child_asked_question)
        return YoungLearnerTrajectory(
            sessions=len(sessions),
            activities_offered=offered,
            activities_done=done,
            done_rate=done / offered if offered else None,
            curiosity_breadth=CuriosityTrajectory.breadth(points),
            engagement_by_session=engagement_by_session,
            engagement_slope=CuriosityTrajectory.ols_slope(engagement_by_session),
            child_question_rate=asked / len(points) if points else None,
            returned=len(sessions) >= CuriosityTrajectory.TWO_SESSIONS,
        )
