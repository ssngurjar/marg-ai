"""The production wiring end to end: inbox → dispatcher → real Orchestrator → outbox → sender.

Only the providers are fakes (no live calls); the safety gate, layer, prompt registry, router,
store and dispatcher are the ones `build_container` wires.
"""

import os
import random
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.channels.whatsapp.payloads import WebhookBody
from app.channels.whatsapp.webhook_parser import WhatsAppWebhookParser
from app.core.errors import ProviderUnavailable
from app.domain.enums import Channel, SafetyCategory
from app.domain.models.base import UserHash
from app.providers.http import RetryPolicy, RetryTiming
from app.providers.ports import ChannelSender, SafetyRequest
from app.store.db import create_engine, create_session_factory
from app.store.repositories.inbox_repository import InboundRecord, InboxRepository
from app.store.repositories.outbox_repository import OutboxRepository
from app.wiring import EngineParts, build_orchestrator, build_turn_dispatcher
from app.worker.turn_dispatcher import TurnDispatcher
from tests.fakes.clock import FixedClock
from tests.fakes.language_model import FakeLanguageModel
from tests.fakes.safety_classifier import FakeSafetyClassifier
from tests.fakes.sender import FakeSender
from tests.fakes.sleeper import FakeSleeper
from tests.support import whatsapp_payloads as wa
from tests.support.app_factory import TEST_PHONE_NUMBER_ID, make_identity, make_settings
from tests.support.parent_answers import HINGLISH_ANSWER

pytestmark = pytest.mark.integration

NOW = datetime.fromtimestamp(int(wa.SENT_AT), tz=UTC) + timedelta(minutes=1)
QUESTION = "Beta ko rang kaise sikhayein?"
GENERATED = str(HINGLISH_ANSWER["answer"])


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


@dataclass(frozen=True, slots=True)
class Pipeline:
    dispatcher: TurnDispatcher
    inbox: InboxRepository
    sender: FakeSender


def wire(engine: AsyncEngine, classifier: FakeSafetyClassifier) -> Pipeline:
    settings = make_settings().model_copy(update={"turn_debounce_ms": 0})
    sessions = create_session_factory(engine)
    clock = FixedClock(NOW)
    sender = FakeSender(clock)
    senders: dict[Channel, ChannelSender] = {Channel.WHATSAPP: sender}
    retry = RetryPolicy(
        timing=RetryTiming(attempts=1),
        clock=clock,
        sleeper=FakeSleeper(clock),
        rng=random.Random(5),  # noqa: S311  # deterministic jitter for tests
    )
    orchestrator = build_orchestrator(
        settings, FakeLanguageModel([HINGLISH_ANSWER]), classifier, clock
    )
    dispatcher = build_turn_dispatcher(
        settings=settings,
        session_factory=sessions,
        engine_parts=EngineParts(
            clock=clock,
            identity=make_identity(),
            retry=retry,
            senders=senders,
            orchestrator=orchestrator,
            outbox=OutboxRepository(sessions),
        ),
    )
    return Pipeline(dispatcher, InboxRepository(sessions), sender)


async def ask(pipeline: Pipeline, question: str) -> None:
    identity = make_identity()
    parsed = WhatsAppWebhookParser.parse(
        WebhookBody.model_validate(wa.webhook([wa.text_message(question)])),
        TEST_PHONE_NUMBER_ID,
        identity,
        NOW,
    )
    records = [
        InboundRecord(
            message=item.inbound,
            address_ciphertext=identity.encrypt_address(
                item.inbound.user_hash, item.wa_id.get_secret_value()
            ),
            raw_payload=item.raw_payload,
        )
        for item in parsed.messages
    ]
    saved = await pipeline.inbox.save(records)
    user: UserHash
    for user in saved.users_with_new_messages:
        pipeline.dispatcher.wake(user)
    await pipeline.dispatcher.wait_until_idle()


async def rows(engine: AsyncEngine, sql: str) -> Sequence[tuple[object, ...]]:
    async with engine.connect() as connection:
        return [tuple(row) for row in (await connection.execute(text(sql))).all()]


async def test_a_parents_question_is_answered_and_every_step_is_recorded(
    engine: AsyncEngine,
) -> None:
    pipeline = wire(engine, FakeSafetyClassifier())
    await ask(pipeline, QUESTION)
    sent = [delivered.part.text or "" for delivered in pipeline.sender.sent]
    assert any(GENERATED in part for part in sent)
    assert await rows(engine, "SELECT step, outcome FROM turn_steps ORDER BY id") == [
        ("route", "ok"),
        ("safety_in", "ok"),
        ("generate", "ok"),
        ("translate", "skipped"),
        ("safety_out", "ok"),
    ]
    assert await rows(
        engine, "SELECT status, route, fixed_reply_kind, prompt_versions FROM turns"
    ) == [("completed", "journey", None, {"parent_answer": "1.0.0"})]


async def test_safety_down_sends_the_holding_reply_and_records_the_failure(
    engine: AsyncEngine,
) -> None:
    down = FakeSafetyClassifier(error=ProviderUnavailable("503", provider="llama_guard"))
    pipeline = wire(engine, down)
    await ask(pipeline, QUESTION)
    sent = " ".join(delivered.part.text or "" for delivered in pipeline.sender.sent)
    assert GENERATED not in sent
    assert len(pipeline.sender.sent) == 1
    assert await rows(engine, "SELECT fixed_reply_kind, failure_step, failure_kind FROM turns") == [
        ("holding", "safety_in", "unavailable")
    ]


async def test_a_crisis_gets_the_helpline_and_its_text_is_not_kept(engine: AsyncEngine) -> None:
    def self_harm(request: SafetyRequest) -> list[SafetyCategory]:
        return [SafetyCategory.SELF_HARM] if request.speaker == "user" else []

    pipeline = wire(engine, FakeSafetyClassifier(flag=self_harm))
    await ask(pipeline, "main thak gayi hoon, sab khatam karna chahti hoon")
    sent = " ".join(delivered.part.text or "" for delivered in pipeline.sender.sent)
    assert "14416" in sent
    assert GENERATED not in sent
    assert await rows(engine, "SELECT route, user_text FROM turns") == [("crisis", None)]
