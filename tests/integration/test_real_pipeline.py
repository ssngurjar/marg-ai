"""The production wiring end to end: inbox → dispatcher → real Orchestrator → outbox → sender.

Only the providers are fakes (no live calls); the safety gate, layer, prompt registry, router,
store and dispatcher are the ones `build_container` wires.
"""

import dataclasses
import os
import random
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.channels.whatsapp.payloads import WebhookBody
from app.channels.whatsapp.webhook_parser import WhatsAppWebhookParser
from app.constants.onboarding_copy import COPY_VERSION
from app.core.errors import ProviderUnavailable
from app.core.types import JsonValue
from app.domain.enums import Channel, PartKind, SafetyCategory
from app.domain.models.base import UserHash
from app.layers.khoj_card_maker import KhojCardMaker
from app.providers.http import RetryPolicy, RetryTiming
from app.providers.ports import ChannelSender, SafetyRequest
from app.store.db import create_engine, create_session_factory
from app.store.repositories.inbox_repository import InboundRecord, InboxRepository
from app.store.repositories.media_blob_repository import MediaBlobRepository
from app.store.repositories.outbox_repository import OutboxRepository
from app.telemetry.curiosity_signal_extractor import CuriositySignalExtractor
from app.wiring import EngineParts, OrchestratorPorts, build_orchestrator, build_turn_dispatcher
from app.worker.turn_dispatcher import TurnDispatcher
from tests.fakes.clock import FixedClock
from tests.fakes.domain_policy import CLEAR, REPLY_CLEAR, policy_answer
from tests.fakes.image import TINY_PNG, FakeImageGenerator
from tests.fakes.language_model import (
    FakeLanguageModel,
    PromptRoutedLanguageModel,
    ScriptedOutput,
)
from tests.fakes.safety_classifier import FakeSafetyClassifier
from tests.fakes.sender import FakeSender
from tests.fakes.sleeper import FakeSleeper
from tests.fakes.voice import VOICE_NOTE, FakeTranscriber, FakeVoice
from tests.support import whatsapp_payloads as wa
from tests.support.app_factory import TEST_PHONE_NUMBER_ID, make_identity, make_settings
from tests.support.child_talk import CHILD_ANSWER, CHILD_REPLY
from tests.support.journey import (
    CARD_HEADLINE,
    CARD_TEXT,
    CURIOSITY_SIGNALS,
    REFLECTION,
    REFLECTION_PRAISE,
    first_choice,
    personalisation_for,
)
from tests.support.parent_answers import HINGLISH_ANSWER
from tests.support.prompts import shipped_registry

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
    voice: FakeVoice | None = None,
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
            "child_talk": FakeLanguageModel([CHILD_REPLY]),
            "curiosity_extract": FakeLanguageModel([CURIOSITY_SIGNALS]),
            "khoj_card_text": FakeLanguageModel([CARD_TEXT]),
        }
    )
    media = MediaBlobRepository(sessions)  # the real table: voice notes stored and loaded
    voice_steps = dataclasses.replace((voice or FakeVoice()).steps(), audio_store=media)
    orchestrator = build_orchestrator(
        settings, OrchestratorPorts(language_model, classifier, voice_steps), clock
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
            media=media,
            signals=CuriositySignalExtractor(language_model, shipped_registry()),
            cards=KhojCardMaker(language_model, FakeImageGenerator(), shipped_registry()),
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
    "media_blobs WHERE user_hash = :h",
    "child_sessions WHERE user_hash = :h",
    "nudge_subscriptions WHERE user_hash = :h",
    "curiosity_signals WHERE learner_id IN (SELECT id FROM learners WHERE owner_user_hash = :h)",
    "turn_steps WHERE turn_id IN (SELECT id FROM turns WHERE user_hash = :h)",
)


def heard(*transcripts: str) -> FakeVoice:
    return FakeVoice(transcriber=FakeTranscriber(list(transcripts)))


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


async def onboarded_parent(engine: AsyncEngine, *, child_talk: bool = False) -> None:
    """The user the journey tests talk to: consented, a parent, with one child (who may talk
    to Marg directly when `child_talk`)."""
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO users (user_hash, channel, address_ciphertext, state, role, "
                "consented_at, language) VALUES (:h, 'whatsapp', :address, 'active', 'parent',"
                " now(), 'hinglish')"
            ),
            {"h": USER_HASH, "address": make_identity().encrypt_address(USER_HASH, wa.FAKE_WA_ID)},
        )
        await connection.execute(
            text(
                "INSERT INTO learners (id, owner_user_hash, relation, nickname, birth_year, "
                "child_talk_consented_at) VALUES (gen_random_uuid(), :h, 'parent', 'Munni', 2021,"
                " CASE WHEN :talk THEN now() END)"
            ),
            {"h": USER_HASH, "talk": child_talk},
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
    first_khoj = pipeline.sender.sent[-2].part
    assert [button.id for button in first_khoj.buttons] == ["jrn:done", "jrn:other"]
    nudge_question = pipeline.sender.sent[-1].part
    assert [button.id for button in nudge_question.buttons] == [
        "nudge:08",
        "nudge:18",
        "nudge:off",
    ]
    await send(pipeline, wa.button_reply("nudge:08", "Subah 8 baje", message_id="wamid.O6"))
    assert await rows(engine, "SELECT enabled, local_time FROM nudge_subscriptions") == [
        (True, time(8, 0))
    ]
    assert await rows(engine, "SELECT activity_id, status FROM learner_activities") == [
        (first_choice().id, "offered")
    ]
    await ask(
        pipeline, "Munni ne kaha parchhai suraj ki wajah se ghoomti hai", message_id="wamid.O5"
    )
    reflection = pipeline.sender.sent[-2].part.text or ""
    assert REFLECTION_PRAISE in reflection
    # after the reflection, an engaged report (2) gets an illustrated card (C6)
    card = pipeline.sender.sent[-1]
    assert card.part.kind is PartKind.IMAGE
    assert (card.part.text or "").startswith(CARD_HEADLINE)
    assert card.image is not None
    assert card.image.data == TINY_PNG
    assert await rows(
        engine,
        "SELECT la.card_blob_id = mb.id, mb.purpose, mb.expires_at - mb.created_at "
        "FROM learner_activities la JOIN media_blobs mb ON mb.id = la.card_blob_id",
    ) == [(True, "khoj_card", timedelta(days=7))]
    assert await rows(engine, "SELECT count(*) FROM turns WHERE route = 'khoj_card'") == [(1,)]
    # after the reply: what the child engaged with (s13), once, for this child
    assert await rows(
        engine,
        "SELECT source, domains, engagement, child_asked_question FROM curiosity_signals",
    ) == [("parent_report", ["earth_sky"], 2, False)]
    assert await rows(
        engine, "SELECT outcome, detail FROM turn_steps WHERE step = 'extract_signals'"
    ) == [("ok", "source=parent_report engagement=2 asked=false")]
    assert await rows(engine, "SELECT status, child_response_summary FROM learner_activities") == [
        ("done", str(REFLECTION["summary_for_record"]))
    ]


async def test_delete_my_data_purges_every_table_after_the_reply_and_hi_starts_fresh(
    engine: AsyncEngine,
) -> None:
    await onboarded_parent(engine)
    pipeline = wire(engine, FakeSafetyClassifier(), voice=heard(QUESTION))
    await send(pipeline, wa.voice_note(message_id="wamid.D0"))  # leaves a stored voice reply
    assert await count(engine, "media_blobs WHERE user_hash = :h") == 1
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


# --- voice, end to end (s06) --------------------------------------------------------------------


async def test_a_voice_question_gets_a_stored_voice_reply_sent_with_its_text(
    engine: AsyncEngine,
) -> None:
    await onboarded_parent(engine)
    voice = heard(QUESTION)
    pipeline = wire(engine, FakeSafetyClassifier(), voice=voice)
    await send(pipeline, wa.voice_note(message_id="wamid.V1"))
    [audio_part] = [sent for sent in pipeline.sender.sent if sent.audio is not None]
    assert audio_part.part.kind is PartKind.AUDIO
    assert audio_part.audio == VOICE_NOTE.model_copy(update={"duration_ms": None})
    assert any(GENERATED in (sent.part.text or "") for sent in pipeline.sender.sent)
    assert await rows(
        engine,
        "SELECT purpose, mime_type, size_bytes, "
        "expires_at - created_at = interval '24 hours' FROM media_blobs",
    ) == [("reply_audio", VOICE_NOTE.mime_type, len(VOICE_NOTE.data), True)]
    assert await rows(engine, "SELECT user_text FROM turns") == [(QUESTION,)]
    steps = await rows(engine, "SELECT step, outcome FROM turn_steps ORDER BY id")
    assert steps[:2] == [("fetch_media", "ok"), ("transcribe", "ok")]
    assert steps[-1] == ("synthesize", "ok")
    assert voice.fetcher.refs[0].provider_media_id == "MEDIA1"


# --- child talk, end to end (s10b §4.16, C13) -----------------------------------------------------


async def test_a_child_talks_answers_are_counted_and_bye_sends_the_parents_summary(
    engine: AsyncEngine,
) -> None:
    await onboarded_parent(engine, child_talk=True)
    pipeline = wire(engine, FakeSafetyClassifier())
    await send(pipeline, wa.button_reply("kid:start", "Main bachcha hoon"))
    assert "Namaste Munni" in (pipeline.sender.sent[-1].part.text or "")
    assert await rows(engine, "SELECT turns_count, ended_at IS NULL FROM child_sessions") == [
        (0, True)
    ]
    await ask(pipeline, "chaand kyun chamakta hai?", message_id="wamid.K2")
    replies = " ".join(sent.part.text or "" for sent in pipeline.sender.sent)
    assert CHILD_ANSWER in replies
    assert await rows(engine, "SELECT turns_count, topics FROM child_sessions") == [
        (1, ["earth_sky"])
    ]
    assert await rows(engine, "SELECT source FROM curiosity_signals") == [("child_words",)]
    await ask(pipeline, "bye", message_id="wamid.K3")
    goodbye = pipeline.sender.sent[-1].part.text or ""
    assert "Mummy-Papa ke liye" in goodbye
    assert "aasmaan aur mausam" in goodbye
    assert "chaand kyun" not in goodbye  # topics, never the child's words
    assert await rows(
        engine,
        "SELECT end_reason, ended_at IS NOT NULL, summary_sent_at IS NOT NULL FROM child_sessions",
    ) == [("child_ended", True, True)]
    assert await rows(engine, "SELECT route FROM turns ORDER BY started_at") == [
        ("child_talk",),
        ("child_talk",),
        ("child_talk",),
    ]


async def test_inside_a_child_session_delete_my_data_deletes_nothing(engine: AsyncEngine) -> None:
    await onboarded_parent(engine, child_talk=True)
    pipeline = wire(engine, FakeSafetyClassifier())
    await send(pipeline, wa.button_reply("kid:start", "Main bachcha hoon"))
    await ask(pipeline, "mera data hatao", message_id="wamid.K4")
    assert "Mummy-Papa karenge" in (pipeline.sender.sent[-1].part.text or "")
    assert await count(engine, "users WHERE user_hash = :h") == 1
    assert await count(engine, "child_sessions WHERE user_hash = :h AND ended_at IS NULL") == 1


async def test_without_consent_the_parent_is_offered_the_switch(engine: AsyncEngine) -> None:
    await onboarded_parent(engine)
    pipeline = wire(engine, FakeSafetyClassifier())
    await ask(pipeline, "Main Munni hoon", message_id="wamid.K5")
    last = pipeline.sender.sent[-1].part
    assert "chalu nahi hai" in (last.text or "")
    assert last.buttons[0].id.startswith("onb:childtalk:yes:")
    assert await count(engine, "child_sessions WHERE user_hash = :h") == 0
