"""The daily child-talk limit against Postgres: the parent's pick commits with the turn, only for
their own child, and is read back with the learners; each turn's context carries every session
the account's children started today, open ones included, with when each last answered (s10b
§4.16; owner, 2026-11-13; data-model `learners`, `child_sessions`)."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.domain.enums import ChildSessionEndReason, DailyTalkLimit
from app.domain.models.learner import Learner, LearnerId
from app.domain.models.writes import (
    ChildSessionEnd,
    ChildSessionStart,
    ChildTalkDailyLimit,
    ChildTalkTurn,
)
from app.domain.rules.child_daily_limit_rules import ChildDailyLimitRules
from app.domain.rules.nudge_schedule import NudgeSchedule
from app.store.db import create_engine, create_session_factory
from app.store.repositories.child_session_repository import ChildSessionRepository
from app.store.repositories.learner_repository import LearnerRepository
from app.store.repositories.turn_repository import TurnRepository
from tests.integration.test_journey_store import (
    FINISHED,
    GOLU,
    MUNNI,
    OTHER,
    PARENT,
    STRANGER_CHILD,
    started,
)
from tests.support.app_factory import make_settings
from tests.support.child_talk import LIMITS

pytestmark = pytest.mark.integration

# A fixed moment, so the test never depends on when in the India day it runs
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=NudgeSchedule.INDIA).astimezone(UTC)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL must point at the docker-compose.test.yml database")
    engine = create_engine(make_settings(database_url=url))
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE users, inbox_messages RESTART IDENTITY CASCADE"))
        for user in (PARENT, OTHER):
            await connection.execute(
                text(
                    "INSERT INTO users (user_hash, channel, state, role, consented_at) "
                    "VALUES (:h, 'whatsapp', 'active', 'parent', now())"
                ),
                {"h": user},
            )
        for learner, owner in ((MUNNI, PARENT), (GOLU, PARENT), (STRANGER_CHILD, OTHER)):
            await connection.execute(
                text(
                    "INSERT INTO learners (id, owner_user_hash, relation, birth_year, "
                    "child_talk_consented_at) VALUES (:id, :owner, 'parent', 2021, now())"
                ),
                {"id": learner, "owner": owner},
            )
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
def turns(engine: AsyncEngine) -> TurnRepository:
    return TurnRepository(create_session_factory(engine))


async def learners_of(sessions: async_sessionmaker[AsyncSession]) -> dict[LearnerId, Learner]:
    async with sessions() as session:
        listed = await LearnerRepository.list_for(session, PARENT)
    return {learner.id: learner for learner in listed}


async def stored_limit(engine: AsyncEngine, learner: LearnerId) -> object:
    async with engine.connect() as connection:
        return (
            await connection.execute(
                text("SELECT child_talk_daily_limit FROM learners WHERE id = :id"),
                {"id": learner},
            )
        ).scalar_one()


# --- the parent's pick ------------------------------------------------------------------------


async def test_a_child_whose_parent_hasnt_picked_has_no_stored_limit(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Every child consented before the limit existed: NULL, so the default 30 minutes."""
    munni = (await learners_of(sessions))[MUNNI]
    assert munni.child_talk_daily_limit is None
    assert await stored_limit(engine, MUNNI) is None
    assert ChildDailyLimitRules.limit_for(munni) == timedelta(minutes=30)


async def test_the_parents_pick_commits_with_the_turn_for_that_child_only(
    turns: TurnRepository, engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    write = ChildTalkDailyLimit(learner_id=MUNNI, limit=DailyTalkLimit.MINUTES_60)
    await turns.finalize(await started(engine), FINISHED, None, [write])
    children = await learners_of(sessions)
    assert children[MUNNI].child_talk_daily_limit is DailyTalkLimit.MINUTES_60
    assert children[GOLU].child_talk_daily_limit is None


async def test_the_next_turn_reads_the_childs_limit_in_its_context(
    turns: TurnRepository, engine: AsyncEngine
) -> None:
    write = ChildTalkDailyLimit(learner_id=GOLU, limit=DailyTalkLimit.NO_LIMIT)
    await turns.finalize(await started(engine), FINISHED, None, [write])
    context = await turns.load_context(await started(engine), recent_exchanges=4)
    limits = {learner.id: learner.child_talk_daily_limit for learner in context.learners}
    assert limits == {MUNNI: None, GOLU: DailyTalkLimit.NO_LIMIT}


async def test_the_parent_can_change_the_limit_any_time(
    turns: TurnRepository, engine: AsyncEngine
) -> None:
    for limit in DailyTalkLimit:
        write = ChildTalkDailyLimit(learner_id=MUNNI, limit=limit)
        await turns.finalize(await started(engine), FINISHED, None, [write])
        assert await stored_limit(engine, MUNNI) == limit.value


async def test_a_limit_for_another_accounts_child_changes_nothing(
    turns: TurnRepository, engine: AsyncEngine
) -> None:
    write = ChildTalkDailyLimit(learner_id=STRANGER_CHILD, limit=DailyTalkLimit.MINUTES_20)
    await turns.finalize(await started(engine), FINISHED, None, [write])
    assert await stored_limit(engine, STRANGER_CHILD) is None


@pytest.mark.parametrize("value", ["10_minutes", "45_minutes", "no limit", "", "30"])
async def test_the_database_refuses_a_limit_that_isnt_a_choice(
    engine: AsyncEngine, value: str
) -> None:
    with pytest.raises(IntegrityError, match="child_talk_daily_limit_valid"):
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE learners SET child_talk_daily_limit = :v WHERE id = :id"),
                {"v": value, "id": MUNNI},
            )
    assert await stored_limit(engine, MUNNI) is None


async def test_deleting_the_parent_takes_the_limits_with_them(
    turns: TurnRepository, engine: AsyncEngine
) -> None:
    write = ChildTalkDailyLimit(learner_id=MUNNI, limit=DailyTalkLimit.MINUTES_20)
    await turns.finalize(await started(engine), FINISHED, None, [write])
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM users WHERE user_hash = :h"), {"h": PARENT})
        remaining = (
            await connection.execute(
                text("SELECT count(*) FROM learners WHERE child_talk_daily_limit IS NOT NULL")
            )
        ).scalar_one()
    assert remaining == 0


# --- the day's sessions -----------------------------------------------------------------------


async def session_at(  # noqa: PLR0913  # one keyword per part of a session a test sets
    sessions: async_sessionmaker[AsyncSession],
    learner: LearnerId,
    *,
    started_at: datetime,
    answered_at: datetime | None,
    ended: tuple[datetime, ChildSessionEndReason] | None,
    turns: int = 2,
) -> UUID:
    """A session through the repository, then moved to fixed times (Postgres stamps now())."""
    session_id = uuid4()
    async with sessions() as session, session.begin():
        await ChildSessionRepository.start(
            session, PARENT, ChildSessionStart(session_id=session_id, learner_id=learner)
        )
        for _ in range(turns):
            await ChildSessionRepository.count_turn(
                session, PARENT, ChildTalkTurn(session_id=session_id, topic=None)
            )
        if ended is not None:
            await ChildSessionRepository.end(
                session, PARENT, ChildSessionEnd(session_id=session_id, reason=ended[1])
            )
        await session.execute(
            text(
                "UPDATE child_sessions SET started_at = :s, last_answered_at = :a, ended_at = :e "
                "WHERE id = :id"
            ),
            {
                "s": started_at,
                "a": answered_at,
                "e": None if ended is None else ended[0],
                "id": session_id,
            },
        )
    return session_id


async def test_an_answered_question_records_when_it_was_answered(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    session_id = uuid4()
    async with sessions() as session, session.begin():
        await ChildSessionRepository.start(
            session, PARENT, ChildSessionStart(session_id=session_id, learner_id=MUNNI)
        )
    async with engine.connect() as connection:
        before = (
            await connection.execute(text("SELECT last_answered_at FROM child_sessions"))
        ).scalar_one()
    assert before is None  # a hello answers nothing
    async with sessions() as session, session.begin():
        await ChildSessionRepository.count_turn(
            session, PARENT, ChildTalkTurn(session_id=session_id, topic=None)
        )
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text("SELECT last_answered_at >= started_at, turns_count FROM child_sessions")
            )
        ).one()
    assert tuple(row) == (True, 1)


async def test_a_session_can_end_on_the_daily_limit(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    session_id = await session_at(
        sessions,
        MUNNI,
        started_at=NOW - timedelta(minutes=6),
        answered_at=NOW,
        ended=(NOW, ChildSessionEndReason.DAILY_LIMIT),
    )
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT end_reason, summary_sent_at IS NOT NULL FROM child_sessions "
                    "WHERE id = :id"
                ),
                {"id": session_id},
            )
        ).one()
    assert tuple(row) == ("daily_limit", True)  # the summary went with the goodbye


async def test_every_session_today_is_read_for_each_child_open_ones_included(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    since = ChildDailyLimitRules.day_started(NOW)
    yesterday = since - timedelta(hours=3)
    await session_at(
        sessions,
        MUNNI,
        started_at=yesterday,
        answered_at=yesterday + timedelta(minutes=9),
        ended=(yesterday + timedelta(minutes=9), ChildSessionEndReason.CHILD_ENDED),
    )
    morning = NOW - timedelta(hours=3)
    await session_at(
        sessions,
        MUNNI,
        started_at=morning,
        answered_at=morning + timedelta(minutes=8),
        ended=(morning + timedelta(minutes=8), ChildSessionEndReason.CHILD_ENDED),
    )
    golu = NOW - timedelta(hours=2)
    await session_at(
        sessions,
        GOLU,
        started_at=golu,
        answered_at=golu + timedelta(minutes=10),
        ended=(golu + timedelta(minutes=10), ChildSessionEndReason.TURN_LIMIT),
    )
    munni_open = NOW - timedelta(minutes=4)
    await session_at(
        sessions, MUNNI, started_at=munni_open, answered_at=munni_open, ended=None, turns=1
    )

    async with sessions() as session:
        read = await ChildSessionRepository.spans_since(session, PARENT, since)

    assert [(span.learner_id, span.started_at, span.end_reason) for span in read] == [
        (MUNNI, morning, ChildSessionEndReason.CHILD_ENDED),
        (GOLU, golu, ChildSessionEndReason.TURN_LIMIT),
        (MUNNI, munni_open, None),
    ]
    assert ChildDailyLimitRules.used_today(MUNNI, read, NOW, LIMITS) == timedelta(minutes=12)
    assert ChildDailyLimitRules.used_today(GOLU, read, NOW, LIMITS) == timedelta(minutes=10)


async def test_a_session_the_child_left_counts_until_its_last_answer_and_a_minute(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Maintenance closed it 10.5 minutes in; the child's last answer came 3 minutes in: 3
    minutes, and at least a minute for that answer (owner, 2026-11-13)."""
    start = NOW - timedelta(hours=1)
    await session_at(
        sessions,
        MUNNI,
        started_at=start,
        answered_at=start + timedelta(minutes=3),
        ended=(start + timedelta(minutes=10.5), ChildSessionEndReason.EXPIRED),
    )
    async with sessions() as session:
        read = await ChildSessionRepository.spans_since(
            session, PARENT, ChildDailyLimitRules.day_started(NOW)
        )
    assert ChildDailyLimitRules.used_today(MUNNI, read, NOW, LIMITS) == timedelta(minutes=4)


async def test_maintenance_closing_a_session_keeps_its_last_answer(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    session_id = uuid4()
    async with sessions() as session, session.begin():
        await ChildSessionRepository.start(
            session, PARENT, ChildSessionStart(session_id=session_id, learner_id=MUNNI)
        )
        await ChildSessionRepository.count_turn(
            session, PARENT, ChildTalkTurn(session_id=session_id, topic=None)
        )
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE child_sessions SET started_at = now() - interval '11 minutes', "
                "last_answered_at = now() - interval '8 minutes'"
            )
        )
    assert await ChildSessionRepository(sessions).close_abandoned(timedelta(minutes=10)) == 1
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT end_reason, ended_at - last_answered_at > interval '7 minutes' "
                    "FROM child_sessions"
                )
            )
        ).one()
    assert tuple(row) == ("expired", True)


async def test_the_turn_context_carries_todays_and_yesterdays_sessions_only(
    turns: TurnRepository, engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Times from the database's own clock: the context reads from yesterday's midnight IST,
    so a session that ran over midnight can be summed up with its own day."""
    async with engine.connect() as connection:
        now = (await connection.execute(text("SELECT now()"))).scalar_one()
    today = ChildDailyLimitRules.day_started(now)
    yesterday = today - timedelta(days=1)
    before_yesterday = yesterday - timedelta(minutes=30)
    await session_at(
        sessions,
        MUNNI,
        started_at=before_yesterday,
        answered_at=before_yesterday,
        ended=(before_yesterday + timedelta(minutes=5), ChildSessionEndReason.CHILD_ENDED),
    )
    late_yesterday = today - timedelta(minutes=30)
    await session_at(
        sessions,
        MUNNI,
        started_at=late_yesterday,
        answered_at=late_yesterday + timedelta(minutes=5),
        ended=(late_yesterday + timedelta(minutes=5), ChildSessionEndReason.CHILD_ENDED),
    )
    await session_at(sessions, GOLU, started_at=today, answered_at=today, ended=None, turns=1)
    context = await turns.load_context(await started(engine), recent_exchanges=4)
    assert [(span.learner_id, span.started_at) for span in context.child_talk_today] == [
        (MUNNI, late_yesterday),
        (GOLU, today),
    ]


async def test_another_accounts_sessions_are_never_read(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await session_at(
        sessions, MUNNI, started_at=NOW - timedelta(hours=1), answered_at=None, ended=None
    )
    async with sessions() as session:
        read = await ChildSessionRepository.spans_since(
            session, OTHER, ChildDailyLimitRules.day_started(NOW)
        )
    assert read == []


async def test_the_daily_limit_is_reached_across_sessions_in_the_database(
    turns: TurnRepository, engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """End to end: the parent picks 20 minutes; two full sessions today reach it."""
    write = ChildTalkDailyLimit(learner_id=MUNNI, limit=DailyTalkLimit.MINUTES_20)
    await turns.finalize(await started(engine), FINISHED, None, [write])
    for hours_ago in (3, 2):
        start = NOW - timedelta(hours=hours_ago)
        await session_at(
            sessions,
            MUNNI,
            started_at=start,
            answered_at=start + timedelta(minutes=10),
            ended=(start + timedelta(minutes=10), ChildSessionEndReason.TURN_LIMIT),
            turns=6,
        )
    munni = (await learners_of(sessions))[MUNNI]
    async with sessions() as session:
        read = await ChildSessionRepository.spans_since(
            session, PARENT, ChildDailyLimitRules.day_started(NOW)
        )
    assert ChildDailyLimitRules.is_reached(munni, read, NOW, LIMITS)
    assert not ChildDailyLimitRules.is_reached(munni, read[:1], NOW, LIMITS)
