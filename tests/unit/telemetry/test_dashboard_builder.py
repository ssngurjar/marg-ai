"""DashboardBuilder: the young-learner section, with the k-anonymity floor applied once
(s13 §4.5, §4.7). No learner id, hash, nickname or text may ever leave it."""

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.domain.enums import ChildSessionEndReason, CuriosityDomain
from app.domain.models.base import UserHash
from app.domain.models.learner import LearnerId
from app.domain.rules.curiosity_trajectory import CuriosityPoint
from app.store.repositories.telemetry_repository import (
    ActivityCounts,
    ChildTalkCounts,
    YoungLearnerData,
)
from app.telemetry.dashboard_builder import DashboardBuilder, YoungLearnerDashboard
from tests.fakes.clock import FixedClock
from tests.fakes.telemetry_reader import FakeTelemetryReader

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)  # a Friday in ISO week 44
D = CuriosityDomain


def child(number: int) -> LearnerId:
    return LearnerId(UUID(int=number))


def parent(number: int) -> UserHash:
    return UserHash(f"{number:064x}")


def point(
    days_ago: float,
    engagement: int = 2,
    domains: frozenset[CuriosityDomain] = frozenset({D.EARTH_SKY}),
    *,
    asked: bool = False,
) -> CuriosityPoint:
    return CuriosityPoint(
        at=NOW - timedelta(days=days_ago),
        domains=domains,
        engagement=engagement,
        child_asked_question=asked,
    )


def cohort(children: int, *, reports_days_ago: tuple[float, ...] = (2.0, 0.5)) -> YoungLearnerData:
    """`children` children of different parents, each with the same reports and activities."""
    data = YoungLearnerData()
    for number in range(1, children + 1):
        learner = child(number)
        data.owners[learner] = parent(number)
        data.reports[learner] = [point(days) for days in reports_days_ago]
        data.activities[learner] = ActivityCounts(offered=4, done=2, with_photo=1, with_counts=1)
    return data


async def build(data: YoungLearnerData, floor: int = 5) -> YoungLearnerDashboard:
    return await DashboardBuilder(FakeTelemetryReader(young=data), FixedClock(NOW)).build(floor)


async def test_fewer_children_than_the_floor_shows_nothing_but_the_notice() -> None:
    board = await build(cohort(4))
    assert board.enough is False
    assert (board.children, board.breadth, board.weeks, board.photos) == (None, [], [], None)


async def test_the_admin_floor_of_one_shows_a_single_family() -> None:
    board = await build(cohort(1), floor=1)
    assert board.enough is True
    assert board.children == 1


async def test_the_headline_counts_children_parents_return_and_done_rate() -> None:
    data = cohort(5)
    data.owners[child(5)] = parent(1)  # two children of one parent
    board = await build(data)
    assert (board.children, board.parents) == (5, None)  # 4 parents: under the floor
    assert board.return_rate == 1.0  # every child came back on a second day
    assert board.median_done_rate == 0.5


async def test_a_child_who_started_less_than_a_day_ago_isnt_counted_for_return() -> None:
    data = cohort(5)
    for number in range(6, 11):
        learner = child(number)
        data.owners[learner] = parent(number)
        data.reports[learner] = [point(0.2)]  # first report 5 hours ago
    board = await build(data)
    assert board.children == 10
    assert board.return_rate == 1.0  # only the 5 older children are judged


async def test_breadth_and_domain_buckets_hide_small_cells() -> None:
    data = cohort(6)
    data.reports[child(6)] = [point(1, domains=frozenset({D.NATURE_LIVING, D.ART_MUSIC}))]
    board = await build(data)
    breadth = {bucket.label: bucket.children for bucket in board.breadth}
    assert breadth == {"0": None, "1": 5, "2": None, "3": None, "4+": None}
    domains = {bucket.label: bucket.children for bucket in board.domains}
    assert domains["earth_sky"] == 5
    assert domains["nature_living"] is None  # one child: hidden
    assert len(domains) == len(CuriosityDomain)


async def test_a_week_reported_by_too_few_children_is_left_out() -> None:
    data = cohort(5, reports_days_ago=(0.5,))  # all in week 44
    data.reports[child(1)].append(point(9))  # one child in week 43
    board = await build(data)
    assert [week.week for week in board.weeks] == ["2026-W44"]


async def test_weekly_engagement_shares_and_question_rate() -> None:
    data = cohort(5, reports_days_ago=())
    levels = [0, 1, 2, 3, 3]
    for number, level in zip(range(1, 6), levels, strict=True):
        data.reports[child(number)] = [point(0.5, engagement=level, asked=level == 3)]
    [week] = (await build(data)).weeks
    assert week.reports == 5
    assert week.level_shares == [0.2, 0.2, 0.2, 0.4]
    assert week.question_rate == 0.4


async def test_child_talk_counts_sessions_and_never_shows_crisis_endings() -> None:
    data = cohort(5)
    for number in range(1, 6):
        data.child_talk[child(number)] = ChildTalkCounts(sessions=number, turns=number * 3)
    data.child_words[child(1)] = [point(1, domains=frozenset({D.NATURE_LIVING}), asked=True)]
    data.end_reasons = {ChildSessionEndReason.CHILD_ENDED: 9, ChildSessionEndReason.CRISIS: 1}
    data.summaries_sent = 7
    board = await build(data)
    talk = board.child_talk
    assert talk is not None
    assert (talk.children, talk.sessions, talk.median_sessions_per_child) == (5, 15, 3)
    assert talk.questions_per_session == pytest.approx(1 / 15)
    assert talk.domains_touched == 1
    assert [(ending.label, ending.sessions) for ending in talk.endings] == [("child_ended", 9)]
    assert talk.summaries_sent == 7


async def test_photos_and_cards_are_totals() -> None:
    data = cohort(5)
    data.cards_sent = 3
    board = await build(data)
    assert board.photos is not None
    assert (board.photos.reports_done, board.photos.reports_with_photo) == (10, 5)
    assert (board.photos.reports_with_counts, board.photos.cards_sent) == (5, 3)


async def test_nothing_identifying_ever_leaves_the_builder() -> None:
    data = cohort(6)
    board = await build(data, floor=1)
    dumped = board.model_dump_json()
    assert not re.search(r"[0-9a-f]{64}", dumped)  # no user hash
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", dumped)  # no learner id
