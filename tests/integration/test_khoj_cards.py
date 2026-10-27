"""Khoj cards against Postgres (s10b §4.13, C6): only for an engaged report, one per child per
day, nothing stored when safety says no."""

import os
import random
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.clock import SystemClock
from app.core.errors import ProviderUnavailable, SafetyUnavailable
from app.domain.enums import Channel, CuriosityDomain, Language, PartKind, SafetyCategory
from app.domain.models.base import TurnId, UserHash
from app.domain.models.curiosity import (
    CuriositySignals,
    CuriositySource,
    ExtractSignals,
    MakeKhojCard,
)
from app.domain.models.learner import LearnerId
from app.layers.khoj_card_maker import KhojCardMaker
from app.providers.http import RetryPolicy, RetryTiming
from app.providers.ports import ChannelSender
from app.safety.safety_gate import SafetyGate
from app.store.db import create_engine, create_session_factory
from app.store.repositories.curiosity_signal_repository import CuriositySignalRepository
from app.store.repositories.khoj_card_repository import KhojCardRepository
from app.store.repositories.media_blob_repository import MediaBlobRepository
from app.store.repositories.outbox_repository import OutboxRepository
from app.store.repositories.user_repository import UserRepository
from app.worker.khoj_card_sender import CardDeps, KhojCardSender
from app.worker.reply_deliverer import DeliveryDeps, DeliverySettings, ReplyDeliverer
from tests.fakes.clock import FixedClock
from tests.fakes.domain_policy import scripted_policy
from tests.fakes.image import FakeImageGenerator
from tests.fakes.language_model import FakeLanguageModel
from tests.fakes.safety_classifier import FakeSafetyClassifier
from tests.fakes.sender import FakeSender
from tests.fakes.sleeper import FakeSleeper
from tests.support.app_factory import make_identity, make_settings
from tests.support.journey import CARD_HEADLINE, CARD_TEXT
from tests.support.prompts import shipped_registry

pytestmark = pytest.mark.integration

PARENT = UserHash("7" * 64)
MUNNI = LearnerId(UUID(int=31))
WA_ID = "919000000003"


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
                "INSERT INTO users (user_hash, channel, address_ciphertext, state, role, "
                "last_inbound_at) VALUES (:h, 'whatsapp', :address, 'active', 'parent', now())"
            ),
            {"h": PARENT, "address": make_identity().encrypt_address(PARENT, WA_ID)},
        )
        await connection.execute(
            text(
                "INSERT INTO learners (id, owner_user_hash, relation, nickname, birth_year) "
                "VALUES (:id, :h, 'parent', 'Munni', 2021)"
            ),
            {"id": MUNNI, "h": PARENT},
        )
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


async def reported(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession], engagement: int
) -> MakeKhojCard:
    """A report turn with its activity and extracted signals, inside the 24-hour window."""
    turn_id, activity_id = TurnId(uuid4()), uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO turns (id, user_hash, status, route, worker_id) "
                "VALUES (:t, :h, 'completed', 'journey', 'w')"
            ),
            {"t": turn_id, "h": PARENT},
        )
        await connection.execute(
            text(
                "INSERT INTO inbox_messages (channel, external_id, user_hash, kind, text, "
                "provider_sent_at, turn_id, status) VALUES ('whatsapp', :e, :h, 'text', 'x', "
                "now(), :t, 'done')"
            ),
            {"e": f"wamid.{uuid4()}", "h": PARENT, "t": turn_id},
        )
        await connection.execute(
            text(
                "INSERT INTO learner_activities (id, learner_id, activity_id, activity_version, "
                "offered_turn_id, status) VALUES (:id, :l, 'shadow-time', 1, :t, 'done')"
            ),
            {"id": activity_id, "l": MUNNI, "t": turn_id},
        )
    extract = ExtractSignals(
        turn_id=turn_id,
        learner_id=MUNNI,
        user_text="Munni ne parchhai dekhi",
        source=CuriositySource(
            learner_id=MUNNI, kind="parent_report", hint_domains=[], activity_title=None
        ),
        child_age=5,
    )
    signals = CuriositySignals(
        domains=[CuriosityDomain.EARTH_SKY], engagement=engagement, child_asked_question=False
    )
    await CuriositySignalRepository(sessions).save(extract, signals, "1.0.0")
    return MakeKhojCard(
        turn_id=turn_id,
        learner_id=MUNNI,
        learner_activity_id=activity_id,
        activity_id="shadow-time",
        activity_title="Parchhai ka khel",
        domains=[CuriosityDomain.EARTH_SKY],
        child_nickname="Munni",
        summary="Munni noticed the shadow moved.",
        reply_register=Language.HINGLISH,
    )


def card_sender(
    sessions: async_sessionmaker[AsyncSession],
    sender: FakeSender,
    classifier: FakeSafetyClassifier | None = None,
) -> KhojCardSender:
    clock = FixedClock(SystemClock().now())  # today, as the database sees it
    senders: dict[Channel, ChannelSender] = {Channel.WHATSAPP: sender}
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
    return KhojCardSender(
        CardDeps(
            maker=KhojCardMaker(
                FakeLanguageModel([CARD_TEXT]), FakeImageGenerator(), shipped_registry()
            ),
            gate=SafetyGate(classifier or FakeSafetyClassifier(), scripted_policy()[0]),
            cards=KhojCardRepository(sessions),
            signals=CuriositySignalRepository(sessions),
            deliverer=deliverer,
            clock=clock,
        ),
        worker_id="test-worker",
    )


async def count(engine: AsyncEngine, sql: str) -> int:
    async with engine.connect() as connection:
        return int((await connection.execute(text(sql))).scalar_one())


async def test_an_engaged_report_gets_its_card_sent_with_the_caption(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    task = await reported(engine, sessions, engagement=2)
    sender = FakeSender(FixedClock(SystemClock().now()))
    outcome = await card_sender(sessions, sender).send(task)
    assert outcome.sent
    [card] = sender.sent
    assert card.part.kind is PartKind.IMAGE
    assert (card.part.text or "").startswith(CARD_HEADLINE)
    assert (
        await count(
            engine, "SELECT count(*) FROM learner_activities WHERE card_blob_id IS NOT NULL"
        )
        == 1
    )


@pytest.mark.parametrize("engagement", [0, 1])
async def test_a_brief_report_gets_no_card(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession], engagement: int
) -> None:
    task = await reported(engine, sessions, engagement=engagement)
    sender = FakeSender(FixedClock(SystemClock().now()))
    outcome = await card_sender(sessions, sender).send(task)
    assert (outcome.sent, outcome.skipped) == (False, "low_engagement")
    assert sender.sent == []
    assert await count(engine, "SELECT count(*) FROM media_blobs") == 0


async def test_one_card_per_child_per_day(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    sender = FakeSender(FixedClock(SystemClock().now()))
    first = await card_sender(sessions, sender).send(await reported(engine, sessions, engagement=3))
    second = await card_sender(sessions, sender).send(
        await reported(engine, sessions, engagement=3)
    )
    assert first.sent
    assert (second.sent, second.skipped) == (False, "card_today")
    assert len(sender.sent) == 1


async def test_a_card_safety_flags_is_never_stored_or_sent(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    task = await reported(engine, sessions, engagement=2)
    flagging = FakeSafetyClassifier(flag=lambda _request: [SafetyCategory.VIOLENT_CRIMES])
    sender = FakeSender(FixedClock(SystemClock().now()))
    outcome = await card_sender(sessions, sender, flagging).send(task)
    assert (outcome.sent, outcome.skipped) == (False, "blocked")
    assert sender.sent == []
    assert await count(engine, "SELECT count(*) FROM media_blobs") == 0


async def test_with_llama_guard_down_no_card_goes_out(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    task = await reported(engine, sessions, engagement=2)
    down = FakeSafetyClassifier(error=ProviderUnavailable("503", provider="llama_guard"))
    sender = FakeSender(FixedClock(SystemClock().now()))
    with pytest.raises(SafetyUnavailable):
        await card_sender(sessions, sender, down).send(task)
    assert sender.sent == []
    assert await count(engine, "SELECT count(*) FROM media_blobs") == 0
