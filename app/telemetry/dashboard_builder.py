"""DashboardBuilder: the parents and young learners section of /dashboard (s13 §4.5, §4.7).

Every child's trajectory is computed by CuriosityTrajectory, then aggregated: headline numbers,
how many domains each child explores, which domains, engagement and the child's own questions
per ISO week, child talk, photos and cards. The k-anonymity floor is applied here, once, to every
number drawn from children: a value from fewer than `floor` children is None ("fewer than N").
Counts only: no learner id, hash, nickname or text leaves this module.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from statistics import median
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from app.core.clock import Clock
from app.domain.enums import ChildSessionEndReason, CuriosityDomain
from app.domain.models.learner import LearnerId
from app.domain.rules.curiosity_trajectory import (
    CuriosityPoint,
    CuriosityTrajectory,
    YoungLearnerTrajectory,
)
from app.store.repositories.telemetry_repository import YoungLearnerData
from app.telemetry.small_count_suppressor import SmallCountSuppressor
from app.telemetry.telemetry_reader import TelemetryReader


class Bucket(BaseModel):
    """A labelled count of children; None when fewer than the floor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    children: int | None


class SessionCount(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    sessions: int


class WeekEngagement(BaseModel):
    """One ISO week's parent reports: the share at each engagement level 0-3, and how often the
    child asked their own question."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    week: str  # "2026-W44"
    reports: int
    level_shares: list[float]  # four shares, levels 0..3, summing to 1
    question_rate: float


class ChildTalkSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    children: int | None
    sessions: int
    median_sessions_per_child: float | None
    questions_per_session: float | None
    domains_touched: int
    endings: list[SessionCount]  # per end reason; crisis endings appear only on /status
    summaries_sent: int


class PhotosAndCards(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reports_done: int
    reports_with_photo: int
    reports_with_counts: int
    cards_sent: int  # forwarding can't be measured: WhatsApp doesn't tell a business


class YoungLearnerDashboard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime
    floor: int
    enough: bool  # False: "Not enough learners yet", and every section below is empty
    children: int | None
    parents: int | None
    return_rate: float | None
    median_done_rate: float | None
    breadth: list[Bucket]
    domains: list[Bucket]
    weeks: list[WeekEngagement]
    child_talk: ChildTalkSummary | None
    photos: PhotosAndCards | None


class DashboardBuilder:
    RETURN_WINDOW: ClassVar[timedelta] = timedelta(hours=24)
    """A child counts toward the return rate once their first session is this old (s13 §4.5)."""
    BREADTH_LABELS: ClassVar[tuple[str, ...]] = ("0", "1", "2", "3", "4+")

    def __init__(self, reader: TelemetryReader, clock: Clock) -> None:
        self._reader = reader
        self._clock = clock

    async def build(self, floor: int) -> YoungLearnerDashboard:
        """Raises StoreError when the database can't be read."""
        data = await self._reader.young_learners()
        now = self._clock.now()
        active = _active_children(data)
        if len(active) < floor:
            return _not_enough(now, floor)
        trajectories: dict[LearnerId, YoungLearnerTrajectory] = {}
        for learner_id in active:
            counts = data.activities.get(learner_id)
            trajectories[learner_id] = CuriosityTrajectory.of(
                data.reports.get(learner_id, []),
                offered=counts.offered if counts else 0,
                done=counts.done if counts else 0,
            )
        parents = {data.owners[learner_id] for learner_id in active if learner_id in data.owners}
        return YoungLearnerDashboard(
            generated_at=now,
            floor=floor,
            enough=True,
            children=len(active),
            parents=SmallCountSuppressor.count(len(parents), floor),
            return_rate=self._return_rate(data, active, trajectories, now, floor),
            median_done_rate=_median_done_rate(trajectories.values()),
            breadth=self._breadth(trajectories.values(), floor),
            domains=_domains(data.reports, active, floor),
            weeks=_weeks(data.reports, active, floor),
            child_talk=_child_talk(data, floor),
            photos=_photos(data, active),
        )

    def _return_rate(
        self,
        data: YoungLearnerData,
        active: set[LearnerId],
        trajectories: Mapping[LearnerId, YoungLearnerTrajectory],
        now: datetime,
        floor: int,
    ) -> float | None:
        """Children who came back ÷ children whose first report is over 24 hours old."""
        eligible: list[LearnerId] = []
        for learner_id in active:
            points = data.reports.get(learner_id, [])
            if points and min(point.at for point in points) <= now - self.RETURN_WINDOW:
                eligible.append(learner_id)
        if SmallCountSuppressor.count(len(eligible), floor) is None:
            return None
        returned = sum(1 for learner_id in eligible if trajectories[learner_id].returned)
        return returned / len(eligible)

    def _breadth(self, trajectories: Iterable[YoungLearnerTrajectory], floor: int) -> list[Bucket]:
        last = len(self.BREADTH_LABELS) - 1
        children_per_label = dict.fromkeys(self.BREADTH_LABELS, 0)
        for trajectory in trajectories:
            label = self.BREADTH_LABELS[min(trajectory.curiosity_breadth, last)]
            children_per_label[label] += 1
        return _buckets(children_per_label, floor)


def _active_children(data: YoungLearnerData) -> set[LearnerId]:
    """Children with at least one activity offered or one report."""
    active = set(data.activities)
    active.update(data.reports)
    return active


def _not_enough(now: datetime, floor: int) -> YoungLearnerDashboard:
    return YoungLearnerDashboard(
        generated_at=now,
        floor=floor,
        enough=False,
        children=None,
        parents=None,
        return_rate=None,
        median_done_rate=None,
        breadth=[],
        domains=[],
        weeks=[],
        child_talk=None,
        photos=None,
    )


def _median_done_rate(trajectories: Iterable[YoungLearnerTrajectory]) -> float | None:
    rates: list[float] = []
    for trajectory in trajectories:
        if trajectory.done_rate is not None:
            rates.append(trajectory.done_rate)
    return median(rates) if rates else None


def _buckets(children_per_label: Mapping[str, int], floor: int) -> list[Bucket]:
    shown = SmallCountSuppressor.counts(children_per_label, floor)
    return [Bucket(label=label, children=children) for label, children in shown.items()]


def _domains(
    reports: Mapping[LearnerId, Sequence[CuriosityPoint]], active: set[LearnerId], floor: int
) -> list[Bucket]:
    """How many children explored each domain in their khojs."""
    children_per_domain = dict.fromkeys((domain.value for domain in CuriosityDomain), 0)
    for learner_id in active:
        explored: set[CuriosityDomain] = set()
        for point in reports.get(learner_id, []):
            explored.update(point.domains)
        for domain in explored:
            children_per_domain[domain.value] += 1
    return _buckets(children_per_domain, floor)


def _weeks(
    reports: Mapping[LearnerId, Sequence[CuriosityPoint]], active: set[LearnerId], floor: int
) -> list[WeekEngagement]:
    """Per ISO week, oldest first; a week reported on by fewer than `floor` children is left
    out entirely."""
    points_by_week: defaultdict[str, list[CuriosityPoint]] = defaultdict(list)
    children_by_week: defaultdict[str, set[LearnerId]] = defaultdict(set)
    for learner_id in active:
        for point in reports.get(learner_id, []):
            year, week, _ = point.at.isocalendar()
            label = f"{year}-W{week:02d}"
            points_by_week[label].append(point)
            children_by_week[label].add(learner_id)
    weeks: list[WeekEngagement] = []
    for label in sorted(points_by_week):
        if SmallCountSuppressor.count(len(children_by_week[label]), floor) is None:
            continue  # too few children that week to show anything about it
        points = points_by_week[label]
        reports_that_week = len(points)
        level_counts = [0, 0, 0, 0]
        asked = 0
        for point in points:
            level_counts[point.engagement] += 1
            if point.child_asked_question:
                asked += 1
        weeks.append(
            WeekEngagement(
                week=label,
                reports=reports_that_week,
                level_shares=[count / reports_that_week for count in level_counts],
                question_rate=asked / reports_that_week,
            )
        )
    return weeks


def _child_talk(data: YoungLearnerData, floor: int) -> ChildTalkSummary:
    sessions_per_child: list[int] = []
    for learner_id, counts in data.child_talk.items():
        if learner_id in data.owners:  # a parent's child, not a student
            sessions_per_child.append(counts.sessions)
    total_sessions = sum(sessions_per_child)
    asked = 0
    touched: set[CuriosityDomain] = set()
    for points in data.child_words.values():
        for point in points:
            touched.update(point.domains)
            if point.child_asked_question:
                asked += 1
    endings: dict[str, int] = {}
    for reason, sessions in data.end_reasons.items():
        if reason is not ChildSessionEndReason.CRISIS:
            endings[reason.value] = sessions
    return ChildTalkSummary(
        children=SmallCountSuppressor.count(len(sessions_per_child), floor),
        sessions=total_sessions,
        median_sessions_per_child=median(sessions_per_child) if sessions_per_child else None,
        questions_per_session=asked / total_sessions if total_sessions else None,
        domains_touched=len(touched),
        endings=[SessionCount(label=label, sessions=count) for label, count in endings.items()],
        summaries_sent=data.summaries_sent,
    )


def _photos(data: YoungLearnerData, active: set[LearnerId]) -> PhotosAndCards:
    done = with_photo = with_counts = 0
    for learner_id in active:
        counts = data.activities.get(learner_id)
        if counts is not None:
            done += counts.done
            with_photo += counts.with_photo
            with_counts += counts.with_counts
    return PhotosAndCards(
        reports_done=done,
        reports_with_photo=with_photo,
        reports_with_counts=with_counts,
        cards_sent=data.cards_sent,
    )
