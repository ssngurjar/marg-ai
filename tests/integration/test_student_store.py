"""Students against Postgres (s12 §9): a plan commits with the reply, one active plan per student,
memory upserts, and everything goes with the user."""

import os
from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import HttpUrl
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.clock import SystemClock
from app.domain.enums import AspirationField, ConstraintKind, RoadmapStatus, Sentiment
from app.domain.models.aspiration import AspirationSignals, ExtractAspiration
from app.domain.models.base import TurnId, UserHash
from app.domain.models.learner import LearnerId
from app.domain.models.student import MemoryUpdate
from app.domain.models.writes import ResolvedRoadmapStep, SaveRoadmap
from app.store.db import create_engine, create_session_factory
from app.store.repositories.aspiration_signal_repository import AspirationSignalRepository
from app.store.repositories.profile_memory_repository import ProfileMemoryRepository
from app.store.repositories.telemetry_repository import TelemetryRepository
from app.store.repositories.turn_repository import TurnRepository
from app.store.repositories.user_repository import UserRepository
from tests.integration.test_journey_store import FINISHED, message, started
from tests.support.app_factory import make_settings

pytestmark = pytest.mark.integration

STUDENT = UserHash("a" * 64)  # the user test_journey_store's helpers start turns for
STEPS = [
    ResolvedRoadmapStep(
        action="Ask your teacher for the NMMS form",
        timeframe="this week",
        cost_inr=None,
        source_url=HttpUrl("https://scholarships.gov.in/public/FAQ/NMSSS_FAQ.pdf"),
    ),
    ResolvedRoadmapStep(action="Register on NSP", timeframe="when it opens", cost_inr=Decimal("0"),
                        source_url=HttpUrl("https://scholarships.gov.in")),
    ResolvedRoadmapStep(action="Practise maths daily", timeframe="daily", cost_inr=None,
                        source_url=None),
]  # fmt: skip
MEMORY = MemoryUpdate(
    summary="The student is in class 8 and wants the NMMS scholarship.",
    ambitions=["NMMS scholarship"],
    constraints=["family money is tight"],
)


def plan(goal: str = "NMMS scholarship") -> SaveRoadmap:
    return SaveRoadmap(goal=goal, steps=STEPS, abandon_roadmap_id=None, prompt_version="1.0.0")


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL must point at the docker-compose.test.yml database")
    engine = create_engine(make_settings(database_url=url))
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE users, inbox_messages RESTART IDENTITY CASCADE"))
        await connection.execute(
            text(
                "INSERT INTO users (user_hash, channel, state, role, grade, consented_at) "
                "VALUES (:h, 'whatsapp', 'active', 'student', 8, now())"
            ),
            {"h": STUDENT},
        )
    yield engine
    await engine.dispose()


@pytest.fixture
def turns(engine: AsyncEngine) -> TurnRepository:
    return TurnRepository(create_session_factory(engine))


async def rows(engine: AsyncEngine, sql: str) -> list[tuple[object, ...]]:
    async with engine.connect() as connection:
        return [tuple(row) for row in (await connection.execute(text(sql))).all()]


async def test_a_plan_commits_with_the_turn_and_loads_into_the_next_context(
    engine: AsyncEngine, turns: TurnRepository
) -> None:
    await turns.finalize(await started(engine), FINISHED, None, [plan()])
    context = await turns.load_context(await started(engine, message("mera plan")), 5)
    roadmap = context.active_roadmap
    assert roadmap is not None
    assert roadmap.goal == "NMMS scholarship"
    assert [step.position for step in roadmap.steps] == [1, 2, 3]
    assert (
        str(roadmap.steps[0].source_url) == "https://scholarships.gov.in/public/FAQ/NMSSS_FAQ.pdf"
    )
    assert roadmap.steps[1].cost_inr == Decimal("0.00")


async def test_a_new_plan_abandons_the_old_one(engine: AsyncEngine, turns: TurnRepository) -> None:
    await turns.finalize(await started(engine), FINISHED, None, [plan("first")])
    await turns.finalize(await started(engine), FINISHED, None, [plan("second")])
    assert await rows(engine, "SELECT goal, status FROM roadmaps ORDER BY created_at, goal") == [
        ("first", RoadmapStatus.ABANDONED.value),
        ("second", RoadmapStatus.ACTIVE.value),
    ]


async def insert_active(engine: AsyncEngine, goal: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO roadmaps (id, user_hash, goal, status, prompt_version) "
                "VALUES (:id, :h, :g, 'active', '1.0.0')"
            ),
            {"id": uuid4(), "h": STUDENT, "g": goal},
        )


async def test_the_database_allows_only_one_active_plan(engine: AsyncEngine) -> None:
    await insert_active(engine, "one")
    with pytest.raises(IntegrityError, match="ux_roadmaps_one_active_per_user"):
        await insert_active(engine, "two")


async def test_memory_is_written_replaced_and_loaded(
    engine: AsyncEngine, turns: TurnRepository
) -> None:
    memories = ProfileMemoryRepository(create_session_factory(engine))
    assert await memories.upsert(STUDENT, MEMORY, TurnId(uuid4()), "1.0.0") is True
    newer = MEMORY.model_copy(update={"ambitions": ["doctor (NEET)"]})
    assert await memories.upsert(STUDENT, newer, TurnId(uuid4()), "1.0.0") is True
    context = await turns.load_context(await started(engine), 5)
    assert context.memory is not None
    assert context.memory.ambitions == ["doctor (NEET)"]
    assert await rows(engine, "SELECT count(*) FROM profile_memory") == [(1,)]


async def test_memory_for_a_deleted_user_is_skipped_not_raised(engine: AsyncEngine) -> None:
    memories = ProfileMemoryRepository(create_session_factory(engine))
    assert await memories.upsert(UserHash("f" * 64), MEMORY, TurnId(uuid4()), "1.0.0") is False


async def test_deleting_the_student_deletes_plans_and_memory(
    engine: AsyncEngine, turns: TurnRepository
) -> None:
    await turns.finalize(await started(engine), FINISHED, None, [plan()])
    await ProfileMemoryRepository(create_session_factory(engine)).upsert(
        STUDENT, MEMORY, TurnId(uuid4()), "1.0.0"
    )
    await UserRepository(create_session_factory(engine)).purge_user(STUDENT)
    for table in ("roadmaps", "roadmap_steps", "profile_memory"):
        assert await rows(engine, f"SELECT count(*) FROM {table}") == [(0,)], table  # noqa: S608  # a fixed table name


# --- aspiration signals (s13 §4.3) ----------------------------------------------------------------

SELF = LearnerId(UUID(int=31))
ASPIRATION = AspirationSignals(
    fields=[AspirationField.MEDICINE],
    specificity=3,
    constraints=[ConstraintKind.MONEY],
    sentiment=Sentiment.POSITIVE,
)


async def add_self_learner(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO learners (id, owner_user_hash, relation, birth_year) "
                "VALUES (:id, :h, 'self', 2012)"
            ),
            {"id": SELF, "h": STUDENT},
        )


def aspiration_task(turn_id: TurnId) -> ExtractAspiration:
    return ExtractAspiration(
        turn_id=turn_id,
        learner_id=SELF,
        user_text="doctor banna hai",
        previous_exchange="",
        grade=8,
        at=SystemClock().now(),
    )


async def test_signals_are_saved_once_per_turn_and_read_for_the_dashboard(
    engine: AsyncEngine,
) -> None:
    await add_self_learner(engine)
    turn = await started(engine)
    sessions = create_session_factory(engine)
    repository = AspirationSignalRepository(sessions)
    assert await repository.save(aspiration_task(turn.turn_id), ASPIRATION, "1.0.0") is True
    assert await repository.save(aspiration_task(turn.turn_id), ASPIRATION, "1.0.0") is True
    data = await TelemetryRepository(sessions).students()
    [point] = data.points[SELF]
    assert (point.specificity, point.fields) == (3, frozenset({AspirationField.MEDICINE}))
    assert point.constraints == frozenset({ConstraintKind.MONEY})


async def test_signals_for_a_deleted_student_are_skipped(engine: AsyncEngine) -> None:
    repository = AspirationSignalRepository(create_session_factory(engine))
    gone = aspiration_task(TurnId(uuid4()))
    assert await repository.save(gone, ASPIRATION, "1.0.0") is False
