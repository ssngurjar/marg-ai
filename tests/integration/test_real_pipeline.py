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
from app.constants.onboarding_copy import COPY_VERSION
from app.core.errors import ProviderUnavailable
from app.core.types import JsonValue
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
from tests.fakes.domain_policy import CLEAR, REPLY_CLEAR, policy_answer
from tests.fakes.language_model import (
    FakeLanguageModel,
    PromptRoutedLanguageModel,
    ScriptedOutput,
)
from tests.fakes.safety_classifier import FakeSafetyClassifier
from tests.fakes.sender import FakeSender
from tests.fakes.sleeper import FakeSleeper
from tests.support import whatsapp_payloads as wa
from tests.support.app_factory import TEST_PHONE_NUMBER_ID, make_identity, make_settings
from tests.support.journey import (
    REFLECTION,
    REFLECTION_PRAISE,
    first_choice,
    personalisation_for,
)
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


def wire(
    engine: AsyncEngine,
    classifier: FakeSafetyClassifier,
    policy: ScriptedOutput = CLEAR,
    reply_policy: ScriptedOutput = REPLY_CLEAR,
) -> Pipeline:
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
    language_model = PromptRoutedLanguageModel(
        {
            "parent_answer": FakeLanguageModel([HINGLISH_ANSWER]),
            "minor_policy": FakeLanguageModel([policy]),
            "reply_policy": FakeLanguageModel([reply_policy]),
            "profile_extraction": EXTRACTION,
            "activity_personalise": FakeLanguageModel([personalisation_for(first_choice())]),
            "parent_reflection": FakeLanguageModel([REFLECTION]),
        }
    )
    orchestrator = build_orchestrator(settings, language_model, classifier, clock)
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


EXTRACTION = FakeLanguageModel(
    [
        {
            "role": None, "grade": None, "subject": None, "district": None, "child_age": None,
            "child_nickname": None, "language": None, "question": None,
        }
    ]
)  # fmt: skip
"""Shared so a test can see whether onboarding needed the model at all."""
USER_HASH = UserHash(make_identity().user_hash("whatsapp", wa.FAKE_WA_ID))
EVERY_USER_TABLE = (
    "users WHERE user_hash = :h",
    "inbox_messages WHERE user_hash = :h",
    "turns WHERE user_hash = :h",
    "outbox_messages WHERE user_hash = :h",
    "consent_events WHERE user_hash = :h",
    "learners WHERE owner_user_hash = :h",
    "turn_steps WHERE turn_id IN (SELECT id FROM turns WHERE user_hash = :h)",
)


async def send(pipeline: Pipeline, payload: dict[str, JsonValue]) -> None:
    identity = make_identity()
    parsed = WhatsAppWebhookParser.parse(
        WebhookBody.model_validate(wa.webhook([payload])), TEST_PHONE_NUMBER_ID, identity, NOW
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


async def ask(pipeline: Pipeline, question: str, *, message_id: str = "wamid.Q1") -> None:
    await send(pipeline, wa.text_message(question, message_id=message_id))


async def onboarded_parent(engine: AsyncEngine) -> None:
    """The user the journey tests talk to: consented, a parent, with one child."""
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO users (user_hash, channel, address_ciphertext, state, role, "
                "consented_at) VALUES (:h, 'whatsapp', :address, 'active', 'parent', now())"
            ),
            {"h": USER_HASH, "address": make_identity().encrypt_address(USER_HASH, wa.FAKE_WA_ID)},
        )
        await connection.execute(
            text(
                "INSERT INTO learners (id, owner_user_hash, relation, nickname, birth_year) "
                "VALUES (gen_random_uuid(), :h, 'parent', 'Munni', 2021)"
            ),
            {"h": USER_HASH},
        )


async def count(engine: AsyncEngine, table_and_filter: str) -> int:
    async with engine.connect() as connection:
        result = await connection.execute(
            text(f"SELECT count(*) FROM {table_and_filter}"),  # noqa: S608  # fixed table names
            {"h": USER_HASH},
        )
        return int(result.scalar_one())


async def rows(engine: AsyncEngine, sql: str) -> Sequence[tuple[object, ...]]:
    async with engine.connect() as connection:
        return [tuple(row) for row in (await connection.execute(text(sql))).all()]


async def test_a_parents_question_is_answered_and_every_step_is_recorded(
    engine: AsyncEngine,
) -> None:
    await onboarded_parent(engine)
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


async def test_llama_guard_down_is_covered_by_the_muse_spark_backup(engine: AsyncEngine) -> None:
    down = FakeSafetyClassifier(error=ProviderUnavailable("429", provider="llama_guard"))
    await onboarded_parent(engine)
    pipeline = wire(engine, down)
    await ask(pipeline, QUESTION)
    sent = " ".join(delivered.part.text or "" for delivered in pipeline.sender.sent)
    assert GENERATED in sent
    assert await rows(
        engine, "SELECT step, detail FROM turn_steps WHERE decision IS NOT NULL ORDER BY id"
    ) == [
        ("safety_in", "decision=allow guard=down"),
        ("safety_out", "decision=allow guard=down"),
    ]


async def test_safety_down_sends_the_holding_reply_and_records_the_failure(
    engine: AsyncEngine,
) -> None:
    down = FakeSafetyClassifier(error=ProviderUnavailable("503", provider="llama_guard"))
    await onboarded_parent(engine)
    model_down = ProviderUnavailable("503", provider="meta_model_api")
    pipeline = wire(engine, down, policy=model_down, reply_policy=model_down)
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

    await onboarded_parent(engine)
    pipeline = wire(engine, FakeSafetyClassifier(flag=self_harm))
    await ask(pipeline, "main thak gayi hoon, sab khatam karna chahti hoon")
    sent = " ".join(delivered.part.text or "" for delivered in pipeline.sender.sent)
    assert "14416" in sent
    assert GENERATED not in sent
    assert await rows(engine, "SELECT route, user_text FROM turns") == [("crisis", None)]


async def test_a_disclosure_only_the_policy_check_sees_gets_the_child_helpline(
    engine: AsyncEngine,
) -> None:
    await onboarded_parent(engine)
    pipeline = wire(engine, FakeSafetyClassifier(), policy=policy_answer(abuse=True))
    await ask(pipeline, "Ghar pe koi mujhe pareshan karta hai, kisi ko mat batana bolta hai")
    sent = " ".join(delivered.part.text or "" for delivered in pipeline.sender.sent)
    assert "1098" in sent
    assert GENERATED not in sent
    assert await rows(engine, "SELECT route, user_text FROM turns") == [("crisis", None)]
    assert await rows(
        engine, "SELECT decision, provider FROM turn_steps WHERE step = 'safety_in'"
    ) == [("crisis", "llama_guard+meta_model_api")]


# --- onboarding and delete-my-data, end to end (s08 §10) -------------------------------------


async def test_a_new_parent_is_onboarded_with_consent_recorded_and_one_child(
    engine: AsyncEngine,
) -> None:
    pipeline = wire(engine, FakeSafetyClassifier())
    await ask(pipeline, "Hello", message_id="wamid.O1")
    await send(pipeline, wa.button_reply("onb:consent:yes", "Haan, theek hai"))
    await send(
        pipeline,
        wa.message(
            "interactive",
            {
                "interactive": {
                    "type": "button_reply",
                    "button_reply": {"id": "onb:role:parent", "title": "Main parent hoon"},
                }
            },
            message_id="wamid.O3",
        ),
    )
    await ask(pipeline, "beti, Munni, 5 saal", message_id="wamid.O4")
    assert await rows(
        engine, "SELECT state, role, language, consented_at IS NOT NULL FROM users"
    ) == [("active", "parent", "hinglish", True)]
    assert await rows(engine, "SELECT relation, nickname, birth_year FROM learners") == [
        ("parent", "Munni", NOW.year - 5)
    ]
    assert await rows(engine, "SELECT kind, prompt_version FROM consent_events ORDER BY id") == [
        ("granted", COPY_VERSION),
        ("child_profile_consent", COPY_VERSION),
    ]
    first_khoj = pipeline.sender.sent[-1].part
    assert [button.id for button in first_khoj.buttons] == ["jrn:done", "jrn:other"]
    assert await rows(engine, "SELECT activity_id, status FROM learner_activities") == [
        (first_choice().id, "offered")
    ]
    await ask(
        pipeline, "Munni ne kaha parchhai suraj ki wajah se ghoomti hai", message_id="wamid.O5"
    )
    reflection = pipeline.sender.sent[-1].part.text or ""
    assert REFLECTION_PRAISE in reflection
    assert await rows(engine, "SELECT status, child_response_summary FROM learner_activities") == [
        ("done", str(REFLECTION["summary_for_record"]))
    ]


async def test_delete_my_data_purges_every_table_after_the_reply_and_hi_starts_fresh(
    engine: AsyncEngine,
) -> None:
    await onboarded_parent(engine)
    pipeline = wire(engine, FakeSafetyClassifier())
    await ask(pipeline, QUESTION, message_id="wamid.D0")
    await ask(pipeline, "mera data hatao", message_id="wamid.D1")
    await send(
        pipeline,
        wa.message(
            "interactive",
            {
                "interactive": {
                    "type": "button_reply",
                    "button_reply": {"id": "onb:delete:yes", "title": "Haan, delete karo"},
                }
            },
            message_id="wamid.D2",
        ),
    )
    last_reply = pipeline.sender.sent[-1].part.text or ""
    assert "delete ho gaya" in last_reply
    for table in EVERY_USER_TABLE:
        assert await count(engine, table) == 0, table
    await ask(pipeline, "Hi", message_id="wamid.D3")
    assert await rows(engine, "SELECT state FROM users") == [("awaiting_consent",)]
