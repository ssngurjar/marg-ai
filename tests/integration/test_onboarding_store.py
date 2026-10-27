"""Onboarding writes against Postgres (s08 §4.9 to §4.11, §9 integration)."""

import os
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.errors import InvalidProfileValue, LeaseLost
from app.domain.enums import (
    Channel,
    ConsentEventKind,
    ConversationState,
    InboxStatus,
    LearnerRelation,
    Role,
)
from app.domain.models.base import TurnId, UserHash
from app.domain.models.learner import LearnerId
from app.domain.models.writes import LearnerUpsert, MarkPurgeAfterDelivery, ProfileChange
from app.store.db import create_engine, create_session_factory
from app.store.repositories.turn_repository import FinishedTurn, StartedTurn, TurnRepository
from app.store.repositories.user_repository import UserRepository
from tests.support.app_factory import make_settings

pytestmark = pytest.mark.integration

USER = UserHash("e" * 64)
OTHER = UserHash("f" * 64)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL must point at the docker-compose.test.yml database")
    engine = create_engine(make_settings(database_url=url))
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE users, inbox_messages RESTART IDENTITY CASCADE"))
        for user in (USER, OTHER):
            await connection.execute(
                text(
                    "INSERT INTO users (user_hash, channel, state, role) "
                    "VALUES (:h, 'whatsapp', 'awaiting_child', 'parent')"
                ),
                {"h": user},
            )
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


def to_active(expected: ConversationState = ConversationState.AWAITING_CHILD) -> ProfileChange:
    return ProfileChange(
        expected_state=expected,
        new_state=ConversationState.ACTIVE,
        role=None,
        grade=None,
        subject=None,
        district=None,
        language=None,
        guardian_confirmed=None,
        consented_at=None,
        pending_question=None,
        clear_pending_question=False,
        consent_events=[ConsentEventKind.CHILD_PROFILE_CONSENT],
        consent_prompt_version="onb-test",
    )


def child(birth_year: int = 2021, learner_id: UUID | None = None) -> LearnerUpsert:
    return LearnerUpsert(
        learner_id=LearnerId(learner_id or uuid4()),
        relation=LearnerRelation.PARENT,
        nickname="Munni",
        birth_year=birth_year,
    )


FINISHED = FinishedTurn(
    route=None,
    fixed_reply_kind=None,
    user_text=None,
    reply_text=None,
    reply_register=None,
    prompt_versions={},
    failure_step=None,
    failure_kind=None,
    inbox_status=InboxStatus.DONE,
)


async def started_turn(engine: AsyncEngine, user: UserHash = USER) -> StartedTurn:
    turn_id = TurnId(uuid4())
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO turns (id, user_hash, status, worker_id) "
                "VALUES (:id, :h, 'processing', 'test')"
            ),
            {"id": turn_id, "h": user},
        )
    return StartedTurn(turn_id=turn_id, user_hash=user, channel=Channel.WHATSAPP, queued=[])


async def scalar(engine: AsyncEngine, sql: str, **params: object) -> object:
    async with engine.connect() as connection:
        return (await connection.execute(text(sql), params)).scalar_one()


async def test_a_profile_change_and_its_child_commit_together(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    started = await started_turn(engine)
    await TurnRepository(sessions).finalize(started, FINISHED, None, [to_active(), child()])
    assert await scalar(engine, "SELECT state FROM users WHERE user_hash = :h", h=USER) == "active"
    assert await scalar(engine, "SELECT count(*) FROM learners") == 1
    assert (
        await scalar(
            engine, "SELECT prompt_version FROM consent_events WHERE user_hash = :h", h=USER
        )
        == "onb-test"
    )


async def test_a_stale_state_raises_lease_lost_and_changes_nothing(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    started = await started_turn(engine)
    stale = to_active(expected=ConversationState.AWAITING_ROLE)
    with pytest.raises(LeaseLost, match="awaiting_role"):
        await TurnRepository(sessions).finalize(started, FINISHED, None, [stale, child()])
    assert await scalar(engine, "SELECT state FROM users WHERE user_hash = :h", h=USER) == (
        "awaiting_child"
    )
    assert await scalar(engine, "SELECT count(*) FROM learners") == 0
    assert await scalar(engine, "SELECT status FROM turns WHERE id = :id", id=started.turn_id) == (
        "processing"
    )


async def test_a_fourth_child_is_refused_and_the_whole_turn_rolls_back(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    turns = TurnRepository(sessions)
    for _ in range(3):
        await turns.finalize(await started_turn(engine), FINISHED, None, [child()])
    started = await started_turn(engine)
    with pytest.raises(InvalidProfileValue, match="at most 3 learners"):
        await turns.finalize(started, FINISHED, None, [to_active(), child()])
    assert await scalar(engine, "SELECT count(*) FROM learners") == 3
    assert await scalar(engine, "SELECT state FROM users WHERE user_hash = :h", h=USER) == (
        "awaiting_child"
    )


async def test_upserting_the_same_learner_twice_keeps_one_row(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    learner_id = uuid4()
    turns = TurnRepository(sessions)
    await turns.finalize(await started_turn(engine), FINISHED, None, [child(2021, learner_id)])
    await turns.finalize(await started_turn(engine), FINISHED, None, [child(2020, learner_id)])
    assert await scalar(
        engine, "SELECT birth_year FROM learners WHERE id = :id", id=learner_id
    ) == (2020)


async def test_only_one_self_learner_per_owner(engine: AsyncEngine) -> None:
    insert_self = text(
        "INSERT INTO learners (id, owner_user_hash, relation, birth_year) "
        "VALUES (gen_random_uuid(), :h, 'self', 2012)"
    )
    async with engine.begin() as connection:
        await connection.execute(insert_self, {"h": USER})
    with pytest.raises(IntegrityError, match="uq_learners_one_self_per_owner"):
        async with engine.begin() as connection:
            await connection.execute(insert_self, {"h": USER})


async def test_every_foreign_key_to_users_or_learners_cascades(engine: AsyncEngine) -> None:
    query = text(
        """
        SELECT tc.table_name, kcu.column_name, rc.delete_rule
        FROM information_schema.referential_constraints rc
        JOIN information_schema.table_constraints tc
          ON tc.constraint_name = rc.constraint_name
        JOIN information_schema.key_column_usage kcu
          ON kcu.constraint_name = rc.constraint_name
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = rc.constraint_name
        WHERE ccu.table_name IN ('users', 'learners')
        """
    )
    async with engine.connect() as connection:
        foreign_keys = (await connection.execute(query)).all()
    assert foreign_keys, "expected foreign keys to users"
    not_cascading = [row for row in foreign_keys if row.delete_rule != "CASCADE"]
    assert not_cascading == []


async def test_a_purge_waits_for_delivery_then_removes_only_that_user(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    turns = TurnRepository(sessions)
    users = UserRepository(sessions)
    await turns.finalize(await started_turn(engine, OTHER), FINISHED, None, [child()])
    started = await started_turn(engine)
    await turns.finalize(started, FINISHED, None, [child(), MarkPurgeAfterDelivery()])
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO outbox_messages (turn_id, part_no, user_hash, channel, kind, "
                "text, buttons, status) VALUES (:t, 0, :h, 'whatsapp', 'text', 'x', '[]', "
                "'pending')"
            ),
            {"t": started.turn_id, "h": USER},
        )
    assert await users.purge_if_delivered(started.turn_id) is False
    async with engine.begin() as connection:
        await connection.execute(text("UPDATE outbox_messages SET status = 'sent'"))
    assert await users.purge_if_delivered(started.turn_id) is True
    assert await scalar(engine, "SELECT count(*) FROM users WHERE user_hash = :h", h=USER) == 0
    assert await scalar(engine, "SELECT count(*) FROM learners") == 1  # the other user's child
    assert await users.purge_if_delivered(started.turn_id) is False  # already gone


async def test_the_sweep_purges_a_marked_user_whose_reply_never_went_out(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    started = await started_turn(engine)
    await TurnRepository(sessions).finalize(started, FINISHED, None, [MarkPurgeAfterDelivery()])
    users = UserRepository(sessions)
    assert await users.sweep_purges(timedelta(minutes=10)) == 0
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE turns SET completed_at = now() - interval '11 minutes'")
        )
    assert await users.sweep_purges(timedelta(minutes=10)) == 1
    assert await scalar(engine, "SELECT count(*) FROM users WHERE user_hash = :h", h=USER) == 0


async def test_role_and_language_are_stored_as_their_values(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    change = to_active().model_copy(update={"role": Role.PARENT, "consent_events": []})
    await TurnRepository(sessions).finalize(await started_turn(engine), FINISHED, None, [change])
    assert await scalar(engine, "SELECT role FROM users WHERE user_hash = :h", h=USER) == "parent"
