"""The parent's summary for a child session left without a goodbye (s10b §4.16, s04 §4.13):
sent once, in the parent's channel, inside the 24-hour window, with topics and never words.

Needs `make test-db-up` and migrations applied (`make test-int` does both).
"""

import asyncio
import random
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.constants.child_talk_copy import TOPIC_LABELS
from app.core.clock import SystemClock
from app.domain.enums import (
    Channel,
    ChildSessionEndReason,
    CuriosityDomain,
    Language,
    PartKind,
)
from app.domain.models.writes import ChildSessionEnd, ChildTalkTurn
from app.providers.http import RetryPolicy, RetryTiming
from app.providers.ports import ChannelSender
from app.safety.safety_gate import SafetyGate
from app.store.repositories.child_session_repository import ChildSessionRepository
from app.store.repositories.media_blob_repository import MediaBlobRepository
from app.store.repositories.outbox_repository import OutboxRepository
from app.store.repositories.user_repository import UserRepository
from app.worker.child_session_summary_sender import ChildSessionSummarySender, SummaryDeps
from app.worker.reply_deliverer import DeliveryDeps, DeliverySettings, ReplyDeliverer
from tests.fakes.clock import FixedClock
from tests.fakes.domain_policy import rules_only_policy
from tests.fakes.safety_classifier import FakeSafetyClassifier
from tests.fakes.sender import FakeSender
from tests.fakes.sleeper import FakeSleeper
from tests.integration.test_child_session_store import MUNNI, PARENT, engine, sessions, started
from tests.support.app_factory import make_identity

pytestmark = pytest.mark.integration
__all__ = ["engine", "sessions"]  # the shared fixtures

FAKE_WA_ID = "919000000001"


def summary_sender(
    sessions: async_sessionmaker[AsyncSession], sender: FakeSender
) -> ChildSessionSummarySender:
    clock = FixedClock(SystemClock().now())  # the database's today
    senders: dict[Channel, ChannelSender] = {Channel.WHATSAPP: sender, Channel.WEB: sender}
    media = MediaBlobRepository(sessions)
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
            audio=media,
            images=media,
        ),
        DeliverySettings(max_attempts=5, part_budget=timedelta(seconds=25)),
    )
    return ChildSessionSummarySender(
        SummaryDeps(
            sessions=ChildSessionRepository(sessions),
            gate=SafetyGate(FakeSafetyClassifier(), rules_only_policy()),
            deliverer=deliverer,
        ),
        worker_id="test-worker",
    )


async def run(engine: AsyncEngine, sql: str, **params: object) -> None:
    async with engine.begin() as connection:
        await connection.execute(text(sql), params)


async def scalar(engine: AsyncEngine, sql: str) -> object:
    async with engine.connect() as connection:
        return (await connection.execute(text(sql))).scalar_one()


async def a_parent_writing_recently(engine: AsyncEngine, *, hours_ago: int = 1) -> None:
    await run(
        engine,
        "UPDATE users SET language = 'hinglish', address_ciphertext = :address, "
        "last_inbound_at = now() - make_interval(hours => :hours) WHERE user_hash = :h",
        address=make_identity().encrypt_address(PARENT, FAKE_WA_ID),
        hours=hours_ago,
        h=PARENT,
    )
    await run(engine, "UPDATE learners SET nickname = 'Munni' WHERE id = :id", id=MUNNI)


async def a_session_the_child_walked_away_from(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> UUID:
    session_id = await started(sessions, MUNNI)
    async with sessions() as session, session.begin():
        await ChildSessionRepository.count_turn(
            session, PARENT, ChildTalkTurn(session_id=session_id, topic=CuriosityDomain.EARTH_SKY)
        )
    await run(
        engine,
        "UPDATE child_sessions SET started_at = now() - interval '11 minutes' WHERE id = :id",
        id=session_id,
    )
    assert await ChildSessionRepository(sessions).close_abandoned(timedelta(minutes=10)) == 1
    return session_id


async def test_the_parent_gets_the_topics_once(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await a_parent_writing_recently(engine)
    await a_session_the_child_walked_away_from(engine, sessions)
    sender = FakeSender(FixedClock(SystemClock().now()))
    summaries = summary_sender(sessions, sender)
    assert await summaries.send_due() == 1
    assert await summaries.send_due() == 0  # never twice
    [sent] = sender.sent
    assert sent.part.kind is PartKind.TEXT
    assert sent.audio is None  # written only, never spoken
    summary = sent.part.text or ""
    assert "Munni" in summary
    assert TOPIC_LABELS[CuriosityDomain.EARTH_SKY][Language.HINGLISH] in summary
    assert await scalar(engine, "SELECT summary_sent_at IS NOT NULL FROM child_sessions")
    assert (
        await scalar(engine, "SELECT fixed_reply_kind FROM turns WHERE route = 'child_talk'")
        == "child_session_end"
    )


async def test_two_workers_send_one_summary(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await a_parent_writing_recently(engine)
    await a_session_the_child_walked_away_from(engine, sessions)
    sender = FakeSender(FixedClock(SystemClock().now()))
    first, second = await asyncio.gather(
        summary_sender(sessions, sender).send_due(), summary_sender(sessions, sender).send_due()
    )
    assert first + second == 1
    assert len(sender.sent) == 1


async def test_after_the_24_hour_window_no_summary_is_sent(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await a_parent_writing_recently(engine, hours_ago=25)
    await a_session_the_child_walked_away_from(engine, sessions)
    sender = FakeSender(FixedClock(SystemClock().now()))
    assert await summary_sender(sessions, sender).send_due() == 0
    assert sender.sent == []
    assert await scalar(engine, "SELECT count(*) FROM outbox_messages") == 0


@pytest.mark.parametrize(
    "reason", [ChildSessionEndReason.CHILD_ENDED, ChildSessionEndReason.CRISIS]
)
async def test_a_session_ended_in_a_turn_gets_nothing_more(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession], reason: ChildSessionEndReason
) -> None:
    """A goodbye already carried the summary; after a crisis the parent gets the crisis
    handling, never a cheerful summary."""
    await a_parent_writing_recently(engine)
    session_id = await started(sessions, MUNNI)
    async with sessions() as session, session.begin():
        await ChildSessionRepository.end(
            session, PARENT, ChildSessionEnd(session_id=session_id, reason=reason)
        )
    sender = FakeSender(FixedClock(SystemClock().now()))
    assert await summary_sender(sessions, sender).send_due() == 0
    assert sender.sent == []


async def test_a_web_parent_gets_it_on_their_page(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await run(
        engine,
        "UPDATE users SET channel = 'web', last_inbound_at = NULL WHERE user_hash = :h",
        h=PARENT,
    )
    await a_session_the_child_walked_away_from(engine, sessions)
    sender = FakeSender(FixedClock(SystemClock().now()))
    assert await summary_sender(sessions, sender).send_due() == 1
    assert await scalar(engine, "SELECT channel FROM outbox_messages") == "web"


async def test_a_parent_deleted_meanwhile_gets_nothing(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await a_parent_writing_recently(engine)
    await a_session_the_child_walked_away_from(engine, sessions)
    repository = ChildSessionRepository(sessions)
    [due] = await repository.due_summaries(10, timedelta(hours=24))
    await run(engine, "DELETE FROM users WHERE user_hash = :h", h=PARENT)
    sender = FakeSender(FixedClock(SystemClock().now()))
    summaries = summary_sender(sessions, sender)
    assert (
        await repository.queue_summary(summaries._summary(due)) is None
    )  # the race, made deterministic
    assert sender.sent == []
