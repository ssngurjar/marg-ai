"""Child sessions against Postgres: one open per account, counts and topics, closing, and
cascade on delete (s10b §4.16, data-model `child_sessions`)."""

import os
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.errors import StoreError
from app.domain.enums import ChildSessionEndReason, CuriosityDomain, Language
from app.domain.models.base import UserHash
from app.domain.models.learner import LearnerId
from app.domain.models.writes import (
    ChildSessionEnd,
    ChildSessionLanguage,
    ChildSessionStart,
    ChildTalkTurn,
)
from app.store.db import create_engine, create_session_factory
from app.store.repositories.child_session_repository import ChildSessionRepository
from tests.support.app_factory import make_settings

pytestmark = pytest.mark.integration

PARENT = UserHash("d" * 64)
OTHER = UserHash("e" * 64)
MUNNI = LearnerId(UUID(int=11))
GOLU = LearnerId(UUID(int=12))
STRANGER_CHILD = LearnerId(UUID(int=13))


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
                    "INSERT INTO users (user_hash, channel, state) "
                    "VALUES (:h, 'whatsapp', 'active')"
                ),
                {"h": user},
            )
        for learner, owner in ((MUNNI, PARENT), (GOLU, PARENT), (STRANGER_CHILD, OTHER)):
            await connection.execute(
                text(
                    "INSERT INTO learners (id, owner_user_hash, relation, birth_year) "
                    "VALUES (:id, :owner, 'parent', 2021)"
                ),
                {"id": learner, "owner": owner},
            )
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


async def started(sessions: async_sessionmaker[AsyncSession], learner: LearnerId) -> UUID:
    session_id = uuid4()
    async with sessions() as session, session.begin():
        await ChildSessionRepository.start(
            session, PARENT, ChildSessionStart(session_id=session_id, learner_id=learner)
        )
    return session_id


async def test_a_started_session_is_open_with_nothing_counted(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    session_id = await started(sessions, MUNNI)
    async with sessions() as session:
        opened = await ChildSessionRepository.open_for(session, PARENT)
    assert opened is not None
    assert (opened.id, opened.learner_id, opened.turns_count, opened.topics, opened.language) == (
        session_id,
        MUNNI,
        0,
        [],
        None,  # the child hasn't asked for a language
    )


async def test_a_language_the_child_asks_for_is_kept_for_the_session_only(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    session_id = await started(sessions, MUNNI)
    async with sessions() as session, session.begin():
        await ChildSessionRepository.set_language(
            session, PARENT, ChildSessionLanguage(session_id=session_id, language=Language.HINDI)
        )
    async with sessions() as session:
        opened = await ChildSessionRepository.open_for(session, PARENT)
    assert opened is not None
    assert opened.language is Language.HINDI
    async with engine.connect() as connection:
        account = (
            await connection.execute(
                text("SELECT language FROM users WHERE user_hash = :h"), {"h": PARENT}
            )
        ).scalar_one()
    assert account is None  # the parent's language is untouched


async def test_a_language_that_isnt_one_is_refused_by_the_database(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO child_sessions (id, learner_id, user_hash) VALUES (:id, :l, :h)"),
            {"id": uuid4(), "l": MUNNI, "h": PARENT},
        )
    with pytest.raises(IntegrityError, match="ck_child_sessions_language_valid"):
        async with engine.begin() as connection:
            await connection.execute(text("UPDATE child_sessions SET language = 'klingon'"))


async def test_turns_are_counted_and_each_topic_kept_once(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    session_id = await started(sessions, MUNNI)
    for topic in (
        CuriosityDomain.EARTH_SKY,
        None,
        CuriosityDomain.NATURE_LIVING,
        CuriosityDomain.EARTH_SKY,
    ):
        async with sessions() as session, session.begin():
            await ChildSessionRepository.count_turn(
                session, PARENT, ChildTalkTurn(session_id=session_id, topic=topic)
            )
    async with sessions() as session:
        opened = await ChildSessionRepository.open_for(session, PARENT)
    assert opened is not None
    assert opened.turns_count == 4
    assert sorted(opened.topics) == [CuriosityDomain.EARTH_SKY, CuriosityDomain.NATURE_LIVING]


async def test_an_ended_session_isnt_open_and_starts_the_cooldown(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    session_id = await started(sessions, MUNNI)
    async with sessions() as session, session.begin():
        await ChildSessionRepository.count_turn(
            session, PARENT, ChildTalkTurn(session_id=session_id, topic=None)
        )
        await ChildSessionRepository.end(
            session,
            PARENT,
            ChildSessionEnd(session_id=session_id, reason=ChildSessionEndReason.CHILD_ENDED),
        )
    async with sessions() as session:
        assert await ChildSessionRepository.open_for(session, PARENT) is None
        assert await ChildSessionRepository.last_ended_at(session, PARENT) is not None
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text("SELECT end_reason, summary_sent_at IS NOT NULL FROM child_sessions")
            )
        ).one()
    assert tuple(row) == ("child_ended", True)


async def test_a_session_where_nothing_was_asked_starts_no_cooldown(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Owner, 2026-10-29: the wait limits screen time; a session with no answered question
    used none."""
    session_id = await started(sessions, MUNNI)
    async with sessions() as session, session.begin():
        await ChildSessionRepository.end(
            session,
            PARENT,
            ChildSessionEnd(session_id=session_id, reason=ChildSessionEndReason.TIME_LIMIT),
        )
    async with sessions() as session:
        assert await ChildSessionRepository.open_for(session, PARENT) is None
        assert await ChildSessionRepository.last_ended_at(session, PARENT) is None


async def test_after_a_crisis_no_summary_is_recorded_as_sent(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    session_id = await started(sessions, MUNNI)
    async with sessions() as session, session.begin():
        await ChildSessionRepository.end(
            session,
            PARENT,
            ChildSessionEnd(session_id=session_id, reason=ChildSessionEndReason.CRISIS),
        )
    async with engine.connect() as connection:
        sent = (
            await connection.execute(text("SELECT summary_sent_at FROM child_sessions"))
        ).scalar_one()
    assert sent is None


async def test_one_account_has_at_most_one_open_session(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await started(sessions, MUNNI)
    with pytest.raises(IntegrityError, match="uq_child_sessions_one_open_per_user"):
        await started(sessions, GOLU)


async def test_a_session_can_only_start_for_the_users_own_child(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(StoreError, match="user's own learner"):
        await started(sessions, STRANGER_CHILD)


async def test_writes_for_another_users_session_change_nothing(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    session_id = await started(sessions, MUNNI)
    async with sessions() as session, session.begin():
        await ChildSessionRepository.count_turn(
            session, OTHER, ChildTalkTurn(session_id=session_id, topic=None)
        )
        await ChildSessionRepository.end(
            session,
            OTHER,
            ChildSessionEnd(session_id=session_id, reason=ChildSessionEndReason.CHILD_ENDED),
        )
        await ChildSessionRepository.set_language(
            session, OTHER, ChildSessionLanguage(session_id=session_id, language=Language.ENGLISH)
        )
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text("SELECT turns_count, ended_at, language FROM child_sessions")
            )
        ).one()
    assert tuple(row) == (0, None, None)


async def test_a_session_the_child_left_is_closed_as_expired_by_maintenance(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    session_id = await started(sessions, MUNNI)
    repository = ChildSessionRepository(sessions)
    assert await repository.close_abandoned(timedelta(minutes=10)) == 0
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE child_sessions SET started_at = now() - interval '11 minutes' "
                "WHERE id = :id"
            ),
            {"id": session_id},
        )
    assert await repository.close_abandoned(timedelta(minutes=10)) == 1
    async with engine.connect() as connection:
        reason = (
            await connection.execute(text("SELECT end_reason FROM child_sessions"))
        ).scalar_one()
    assert reason == "expired"


async def test_deleting_the_parent_deletes_the_sessions(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await started(sessions, MUNNI)
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM users WHERE user_hash = :h"), {"h": PARENT})
        remaining = (
            await connection.execute(text("SELECT count(*) FROM child_sessions"))
        ).scalar_one()
    assert remaining == 0
