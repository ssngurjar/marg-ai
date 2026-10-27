"""Curiosity signals against Postgres: once per turn, gone with the child, and the trajectory
read back from them (s13 §4.4, §4.5)."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domain.enums import CuriosityDomain
from app.domain.models.base import TurnId, UserHash
from app.domain.models.curiosity import CuriositySignals, CuriositySource, ExtractSignals
from app.domain.models.learner import LearnerId
from app.store.db import create_engine, create_session_factory
from app.store.repositories.curiosity_signal_repository import CuriositySignalRepository
from tests.support.app_factory import make_settings

pytestmark = pytest.mark.integration

PARENT = UserHash("9" * 64)
MUNNI = LearnerId(UUID(int=21))
DAY_ONE = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL must point at the docker-compose.test.yml database")
    engine = create_engine(make_settings(database_url=url))
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE users, inbox_messages RESTART IDENTITY CASCADE"))
        await connection.execute(
            text("INSERT INTO users (user_hash, channel, state) VALUES (:h, 'whatsapp', 'active')"),
            {"h": PARENT},
        )
        await connection.execute(
            text(
                "INSERT INTO learners (id, owner_user_hash, relation, birth_year) "
                "VALUES (:id, :h, 'parent', 2021)"
            ),
            {"id": MUNNI, "h": PARENT},
        )
    yield engine
    await engine.dispose()


async def turn_at(engine: AsyncEngine, at: datetime) -> TurnId:
    turn_id = TurnId(uuid4())
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO turns (id, user_hash, status, route, worker_id, started_at) "
                "VALUES (:id, :h, 'completed', 'journey', 'w', :at)"
            ),
            {"id": turn_id, "h": PARENT, "at": at},
        )
    return turn_id


def task(turn_id: TurnId) -> ExtractSignals:
    return ExtractSignals(
        turn_id=turn_id,
        learner_id=MUNNI,
        user_text="Munni ne parchhai dekhi",
        source=CuriositySource(
            learner_id=MUNNI, kind="parent_report", hint_domains=[], activity_title=None
        ),
        child_age=5,
    )


def signals(engagement: int, *domains: CuriosityDomain, asked: bool = False) -> CuriositySignals:
    return CuriositySignals(
        domains=list(domains), engagement=engagement, child_asked_question=asked
    )


async def test_a_retried_task_saves_its_signals_once(engine: AsyncEngine) -> None:
    repository = CuriositySignalRepository(create_session_factory(engine))
    turn_id = await turn_at(engine, DAY_ONE)
    assert await repository.save(task(turn_id), signals(2, CuriosityDomain.EARTH_SKY), "1.0.0")
    assert await repository.save(task(turn_id), signals(3, CuriosityDomain.ART_MUSIC), "1.0.0")
    async with engine.connect() as connection:
        saved = (
            await connection.execute(text("SELECT engagement, domains FROM curiosity_signals"))
        ).all()
    assert [tuple(row) for row in saved] == [(2, ["earth_sky"])]


async def test_signals_for_a_user_deleted_meanwhile_are_dropped(engine: AsyncEngine) -> None:
    repository = CuriositySignalRepository(create_session_factory(engine))
    turn_id = await turn_at(engine, DAY_ONE)
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM users WHERE user_hash = :h"), {"h": PARENT})
    assert not await repository.save(task(turn_id), signals(1), "1.0.0")


async def test_the_trajectory_is_read_back_across_sessions(engine: AsyncEngine) -> None:
    repository = CuriositySignalRepository(create_session_factory(engine))
    plan = [
        (DAY_ONE, signals(1, CuriosityDomain.EARTH_SKY)),
        (DAY_ONE + timedelta(days=1), signals(2, CuriosityDomain.NATURE_LIVING)),
        (DAY_ONE + timedelta(days=2), signals(3, CuriosityDomain.EARTH_SKY, asked=True)),
    ]
    for at, extracted in plan:
        await repository.save(task(await turn_at(engine, at)), extracted, "1.0.0")
    async with engine.begin() as connection:
        for status in ("done", "done", "skipped"):
            await connection.execute(
                text(
                    "INSERT INTO learner_activities (id, learner_id, activity_id, "
                    "activity_version, offered_turn_id, status) VALUES (gen_random_uuid(), :l, "
                    "'shadow-time', 1, (SELECT id FROM turns LIMIT 1), :status)"
                ),
                {"l": MUNNI, "status": status},
            )
    trajectory = await repository.trajectory_for(MUNNI)
    assert trajectory.sessions == 3
    assert trajectory.engagement_by_session == [1, 2, 3]
    assert trajectory.engagement_slope == pytest.approx(1.0)
    assert trajectory.curiosity_breadth == 2
    assert (trajectory.activities_offered, trajectory.activities_done) == (3, 2)
    assert trajectory.child_question_rate == pytest.approx(1 / 3)
