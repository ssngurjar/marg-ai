"""The daily khoj message against Postgres (s10b §4.11): opt-in, who is due, the skip rules, and
the template part going out through the outbox, outside the 24-hour window."""

import os
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.domain.enums import Channel, Language, PartKind
from app.domain.models.base import UserHash
from app.domain.models.writes import NudgePreference
from app.domain.rules.nudge_schedule import NudgeSchedule
from app.providers.http import RetryPolicy, RetryTiming
from app.providers.ports import ChannelSender
from app.safety.safety_gate import SafetyGate
from app.store.db import create_engine, create_session_factory
from app.store.repositories.nudge_repository import NudgeRepository
from app.store.repositories.outbox_repository import OutboxRepository
from app.store.repositories.user_repository import UserRepository
from app.worker.nudge_sender import NudgeSender, NudgeSettings, nudge_templates
from app.worker.reply_deliverer import DeliveryDeps, DeliverySettings, ReplyDeliverer
from tests.fakes.clock import FixedClock
from tests.fakes.domain_policy import scripted_policy
from tests.fakes.safety_classifier import FakeSafetyClassifier
from tests.fakes.sender import FakeSender
from tests.fakes.sleeper import FakeSleeper
from tests.fakes.voice import MemoryReplyAudioStore
from tests.support.app_factory import make_identity, make_settings

pytestmark = pytest.mark.integration

PARENT = UserHash("f" * 64)
WA_ID = "919000000002"
MORNING = datetime(2026, 10, 28, 8, 0, tzinfo=NudgeSchedule.INDIA).astimezone(UTC)
TEMPLATES = nudge_templates("marg_daily_khoj", "marg_daily_khoj_hinglish")


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL must point at the docker-compose.test.yml database")
    engine = create_engine(make_settings(database_url=url))
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE users, inbox_messages RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


async def parent(
    engine: AsyncEngine,
    user_hash: UserHash = PARENT,
    *,
    role: str = "parent",
    language: str | None = "hinglish",
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO users (user_hash, channel, address_ciphertext, state, role, "
                "consented_at, language) VALUES (:h, 'whatsapp', :address, 'active', :role, "
                "now(), :language)"
            ),
            {
                "h": user_hash,
                "address": make_identity().encrypt_address(user_hash, WA_ID),
                "role": role,
                "language": language,
            },
        )


async def opt_in(
    sessions: async_sessionmaker[AsyncSession], user_hash: UserHash = PARENT, hour: int = 8
) -> None:
    async with sessions() as session, session.begin():
        await NudgeRepository.set_preference(
            session, user_hash, NudgePreference(enabled=True, local_time=time(hour, 0))
        )


async def make_due(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE nudge_subscriptions SET next_due_at = :due"),
            {"due": MORNING - timedelta(minutes=1)},
        )


async def rows(engine: AsyncEngine, sql: str) -> list[tuple[object, ...]]:
    async with engine.connect() as connection:
        return [tuple(row) for row in (await connection.execute(text(sql))).all()]


def sender_for(
    sessions: async_sessionmaker[AsyncSession], sender: FakeSender, *, daily_limit: int = 200
) -> NudgeSender:
    clock = FixedClock(MORNING)
    senders: dict[Channel, ChannelSender] = {Channel.WHATSAPP: sender}
    deliverer = ReplyDeliverer(
        DeliveryDeps(
            outbox=OutboxRepository(sessions),
            users=UserRepository(sessions),
            senders=senders,
            identity=make_identity(),
            retry=RetryPolicy(
                timing=RetryTiming(attempts=1),
                clock=clock,
                sleeper=FakeSleeper(clock),
                rng=random.Random(5),  # noqa: S311  # deterministic jitter for tests
            ),
            clock=clock,
            audio=MemoryReplyAudioStore(),
            images=MemoryReplyAudioStore(),
        ),
        DeliverySettings(max_attempts=5, part_budget=timedelta(seconds=25)),
    )
    return NudgeSender(
        NudgeRepository(sessions),
        deliverer,
        SafetyGate(FakeSafetyClassifier(), scripted_policy()[0]),
        clock,
        NudgeSettings(templates=TEMPLATES, daily_limit=daily_limit, worker_id="test-worker"),
    )


async def send_at(
    sessions: async_sessionmaker[AsyncSession], now: datetime, *, daily_limit: int = 200
) -> list[object]:
    repository = NudgeRepository(sessions)
    sender = sender_for(sessions, FakeSender(FixedClock(now)), daily_limit=daily_limit)
    result = await repository.send_due(sender._batch, now)  # the batch under test
    return [*result.sent]


# --- opting in and out ---------------------------------------------------------------------------


async def test_opting_in_schedules_the_next_morning_in_india(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await parent(engine)
    await opt_in(sessions)
    [(enabled, local, due_hour)] = await rows(
        engine,
        "SELECT enabled, local_time, extract(hour FROM next_due_at AT TIME ZONE 'Asia/Kolkata') "
        "FROM nudge_subscriptions",
    )
    assert (enabled, local, int(str(due_hour))) == (True, time(8, 0), 8)


async def test_opting_out_clears_the_time_and_records_when(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await parent(engine)
    await opt_in(sessions)
    async with sessions() as session, session.begin():
        await NudgeRepository.set_preference(
            session, PARENT, NudgePreference(enabled=False, local_time=None)
        )
    assert await rows(
        engine,
        "SELECT enabled, local_time, next_due_at, opted_out_at IS NOT NULL "
        "FROM nudge_subscriptions",
    ) == [(False, None, None, True)]


async def test_deleting_the_parent_deletes_the_subscription(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await parent(engine)
    await opt_in(sessions)
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM users WHERE user_hash = :h"), {"h": PARENT})
    assert await rows(engine, "SELECT count(*) FROM nudge_subscriptions") == [(0,)]


# --- sending -------------------------------------------------------------------------------------


async def test_a_due_parent_gets_one_template_part_and_tomorrows_time(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await parent(engine)
    await opt_in(sessions)
    await make_due(engine)
    sent = await send_at(sessions, MORNING)
    assert len(sent) == 1
    assert await rows(
        engine, "SELECT route, status, fixed_reply_kind, reply_register FROM turns"
    ) == [("nudge", "completed", "nudge", "hinglish")]
    [(kind, template, part_text)] = await rows(
        engine, "SELECT kind, template, text FROM outbox_messages"
    )
    assert (kind, part_text) == ("template", None)
    assert template == {
        "name": "marg_daily_khoj_hinglish",
        "language_code": "en",
        "button_payloads": ["jrn:today"],
    }
    [(next_due, last_sent)] = await rows(
        engine, "SELECT next_due_at, last_sent_at FROM nudge_subscriptions"
    )
    assert next_due == MORNING + timedelta(days=1)
    assert last_sent == MORNING


async def test_a_hindi_parent_gets_the_hindi_template(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await parent(engine, language="hindi")
    await opt_in(sessions)
    await make_due(engine)
    await send_at(sessions, MORNING)
    [(template,)] = await rows(engine, "SELECT template FROM outbox_messages")
    assert template == {
        "name": "marg_daily_khoj",
        "language_code": "hi",
        "button_payloads": ["jrn:today"],
    }


async def test_nothing_is_sent_in_quiet_hours_and_the_parent_is_rescheduled(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await parent(engine)
    await opt_in(sessions)
    await make_due(engine)
    night = datetime(2026, 10, 28, 21, 0, tzinfo=NudgeSchedule.INDIA).astimezone(UTC)
    assert await send_at(sessions, night) == []
    assert await rows(engine, "SELECT count(*) FROM turns") == [(0,)]
    [(next_due,)] = await rows(engine, "SELECT next_due_at FROM nudge_subscriptions")
    assert next_due == MORNING + timedelta(days=1)


async def test_a_parent_who_already_did_a_khoj_today_isnt_nudged(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await parent(engine)
    await opt_in(sessions)
    await make_due(engine)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO turns (id, user_hash, status, route, worker_id, started_at) "
                "VALUES (gen_random_uuid(), :h, 'completed', 'journey', 'w', :at)"
            ),
            {"h": PARENT, "at": MORNING - timedelta(hours=1)},
        )
    assert await send_at(sessions, MORNING) == []
    assert await rows(engine, "SELECT count(*) FROM turns WHERE route = 'nudge'") == [(0,)]


async def test_the_daily_cap_holds_across_all_parents(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    second = UserHash("a1" * 32)
    for user in (PARENT, second):
        await parent(engine, user)
        await opt_in(sessions, user)
    await make_due(engine)
    assert len(await send_at(sessions, MORNING, daily_limit=1)) == 1
    assert await rows(engine, "SELECT count(*) FROM turns WHERE route = 'nudge'") == [(1,)]


@pytest.mark.parametrize("role", ["teacher"])
async def test_only_parents_are_nudged(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession], role: str
) -> None:
    await parent(engine, role=role)
    await opt_in(sessions)
    await make_due(engine)
    assert await send_at(sessions, MORNING) == []


async def test_a_parent_not_yet_due_isnt_claimed(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await parent(engine)
    await opt_in(sessions, hour=18)
    assert await send_at(sessions, MORNING) == []


async def test_the_nudge_is_delivered_even_days_after_the_last_message(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Templates are the one part the 24-hour window doesn't stop (s04 §4.10)."""
    await parent(engine)
    await opt_in(sessions)
    await make_due(engine)
    sender = FakeSender(FixedClock(MORNING))
    assert await sender_for(sessions, sender).send_due() == 1
    [delivered] = sender.sent
    assert delivered.part.kind is PartKind.TEMPLATE
    assert delivered.address == WA_ID
    assert await rows(engine, "SELECT status FROM outbox_messages") == [("sent",)]


def test_every_language_has_a_template() -> None:
    assert set(TEMPLATES) == set(Language)
