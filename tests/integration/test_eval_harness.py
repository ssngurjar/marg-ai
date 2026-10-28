"""The eval harness's database work against the test Postgres (s15 §9 integration): a run's own
database is created, migrated and dropped; a case's user is seeded as onboarding would leave
them; a turn is read back with its steps and parts.

Needs `make test-db-up` and migrations applied (`make test-int` does both).
"""

import os
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.errors import ConfigError
from app.domain.enums import Language, LearnerRelation, Role, Route
from app.domain.models.base import TurnId, UserHash
from app.evals.eval_harness import EvalHarness
from app.store.db import create_engine, create_session_factory
from app.store.eval_database import EvalDatabase
from app.store.repositories.eval_repository import (
    EvalRepository,
    EvalSeed,
    SeedActivity,
    SeedLearner,
)
from tests.support.app_factory import make_settings

pytestmark = pytest.mark.integration

PARENT = UserHash("e" * 64)


@pytest.fixture
def admin_url() -> SecretStr:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL must point at the docker-compose.test.yml database")
    return SecretStr(url)


@pytest.fixture
async def engine(admin_url: SecretStr) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(make_settings(database_url=admin_url.get_secret_value()))
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE users, inbox_messages RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()


async def database_exists(admin_url: SecretStr, name: str) -> bool:
    engine = create_async_engine(admin_url.get_secret_value())
    try:
        async with engine.connect() as connection:
            found = await connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
            )
            return found.first() is not None
    finally:
        await engine.dispose()


async def test_a_run_database_is_created_migrated_and_dropped(admin_url: SecretStr) -> None:
    name = f"marg_eval_test_{uuid4().hex[:8]}"
    url = await EvalDatabase.create(admin_url, name)
    try:
        await EvalHarness.migrate(url, timedelta(minutes=3))
        migrated = create_async_engine(url.get_secret_value())
        try:
            async with migrated.connect() as connection:
                tables = (
                    await connection.execute(text("SELECT to_regclass('public.turns') IS NOT NULL"))
                ).scalar_one()
        finally:
            await migrated.dispose()
        assert tables is True
    finally:
        await EvalDatabase.drop(admin_url, name)
    assert not await database_exists(admin_url, name)


@pytest.mark.parametrize(
    "name",
    ["marg", "marg_eval_", "marg_eval_x; DROP DATABASE marg", 'marg_eval_a"b', "MARG_EVAL_A"],
)
async def test_only_marg_eval_names_reach_sql(admin_url: SecretStr, name: str) -> None:
    with pytest.raises(ConfigError, match="doesn't match marg_eval_"):
        await EvalDatabase.create(admin_url, name)
    with pytest.raises(ConfigError, match="doesn't match marg_eval_"):
        await EvalDatabase.drop(admin_url, name)


async def test_a_case_user_is_seeded_as_onboarding_would_leave_them(engine: AsyncEngine) -> None:
    evals = EvalRepository(create_session_factory(engine))
    await evals.seed(
        EvalSeed(
            user_hash=PARENT,
            role=Role.PARENT,
            grade=None,
            subject=None,
            district=None,
            language=Language.HINGLISH,
            learners=[
                SeedLearner(LearnerRelation.PARENT, "Munni", 2021, child_talk_consented=True)
            ],
            open_activity=SeedActivity("leaf-families", 1),
            consent_copy_version="onb-test",
        )
    )
    async with engine.connect() as connection:
        user = (
            await connection.execute(
                text("SELECT channel, state, role, consented_at IS NOT NULL FROM users")
            )
        ).one()
        learner = (
            await connection.execute(
                text("SELECT nickname, child_talk_consented_at IS NOT NULL FROM learners")
            )
        ).one()
        offered = (
            await connection.execute(text("SELECT activity_id, status FROM learner_activities"))
        ).one()
        consents = (await connection.execute(text("SELECT kind FROM consent_events"))).all()
    assert tuple(user) == ("web", "active", "parent", True)
    assert tuple(learner) == ("Munni", True)
    assert tuple(offered) == ("leaf-families", "offered")
    assert [row[0] for row in consents] == ["granted"]


async def test_a_brand_new_user_is_seeded_at_new_without_consent(engine: AsyncEngine) -> None:
    evals = EvalRepository(create_session_factory(engine))
    await evals.seed(
        EvalSeed(
            user_hash=PARENT, role=None, grade=None, subject=None, district=None, language=None,
            learners=[], open_activity=None, consent_copy_version="onb-test",
        )
    )  # fmt: skip
    async with engine.connect() as connection:
        state = (await connection.execute(text("SELECT state, consented_at FROM users"))).one()
        consents = (await connection.execute(text("SELECT count(*) FROM consent_events"))).one()
    assert tuple(state) == ("new", None)
    assert consents[0] == 0


async def test_a_turn_is_read_back_with_its_steps_and_parts(engine: AsyncEngine) -> None:
    evals = EvalRepository(create_session_factory(engine))
    turn_id = TurnId(uuid4())
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO users (user_hash, channel, state) VALUES (:h, 'web', 'active')"),
            {"h": PARENT},
        )
        await connection.execute(
            text(
                "INSERT INTO turns (id, user_hash, status, route, reply_text, reply_register, "
                "worker_id, completed_at) VALUES (:t, :h, 'completed', 'journey', 'Shabash!', "
                "'hinglish', 'w', now())"
            ),
            {"t": turn_id, "h": PARENT},
        )
        await connection.execute(
            text(
                "INSERT INTO turn_steps (turn_id, step, outcome, failure_kind, started_at, "
                "duration_ms, cost_usd) VALUES (:t, 'generate', 'failed', 'timeout', now(), 12000,"
                " 0.003)"
            ),
            {"t": turn_id},
        )
        await connection.execute(
            text(
                "INSERT INTO outbox_messages (turn_id, part_no, user_hash, channel, kind, text, "
                "status) VALUES (:t, 0, :h, 'web', 'text', 'Shabash!', 'sent')"
            ),
            {"t": turn_id, "h": PARENT},
        )
    snapshot = await evals.snapshot(turn_id)
    assert (snapshot.route, snapshot.reply_text, snapshot.reply_register) == (
        Route.JOURNEY, "Shabash!", Language.HINGLISH,
    )  # fmt: skip
    [step] = snapshot.steps
    assert (step.step, step.outcome, step.failure_kind) == ("generate", "failed", "timeout")
    [part] = snapshot.parts
    assert (part.kind, part.text, part.status) == ("text", "Shabash!", "sent")
    assert await evals.turns_after(PARENT, turn_id) == []
    assert await evals.stored_media(PARENT) == 0
