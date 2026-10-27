"""The turn engine against real Postgres (s04 §9 integration; exception E1).

Needs `make test-db-up` and migrations applied (`make test-int` does both). Each test builds the
real stores, processor, deliverer and dispatcher around a fake orchestrator and a fake sender.
"""

import asyncio
import os
import random
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.channels.whatsapp.payloads import WebhookBody
from app.channels.whatsapp.webhook_parser import WhatsAppWebhookParser
from app.core.errors import ProviderError, ProviderRejected, ProviderUnavailable
from app.core.types import JsonValue
from app.domain.enums import (
    Channel,
    FixedReplyKind,
    OutboxStatus,
    PartKind,
    Route,
    StepName,
    StepOutcome,
)
from app.domain.models.base import UserHash
from app.domain.models.reply import ReplyButton
from app.domain.models.turn import QueuedMessage
from app.pipeline.step_models import StepUsage
from app.providers.http import RetryPolicy, RetryTiming
from app.providers.ports import ChannelSender
from app.safety.safety_gate import SafetyGate
from app.store.db import create_engine, create_session_factory
from app.store.repositories.inbox_repository import InboundRecord, InboxRepository
from app.store.repositories.outbox_repository import OutboxRepository
from app.store.repositories.turn_repository import TurnRepository
from app.store.repositories.turn_step_repository import TurnStepRepository
from app.worker.database_step_recorder import DatabaseStepRecorder
from app.worker.reply_deliverer import DeliveryDeps, DeliverySettings, ReplyDeliverer
from app.worker.turn_dispatcher import DispatcherDeps, DispatcherSettings, TurnDispatcher
from app.worker.turn_processor import TurnDeps, TurnProcessor, TurnSettings
from tests.fakes.clock import FixedClock
from tests.fakes.orchestrator import FakeOrchestrator, ScriptedReply
from tests.fakes.sender import FakeSender
from tests.fakes.sleeper import FakeSleeper
from tests.support import whatsapp_payloads as wa
from tests.support.app_factory import TEST_PHONE_NUMBER_ID, make_identity, make_settings

pytestmark = pytest.mark.integration

SENT_AT = datetime.fromtimestamp(int(wa.SENT_AT), tz=UTC)
NOW = SENT_AT + timedelta(minutes=1)  # the app's clock: just after the user wrote


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL must point at the docker-compose.test.yml database")
    return url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(make_settings(database_url=database_url))
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE users, inbox_messages RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()


@dataclass
class Engine:
    sessions: async_sessionmaker[AsyncSession]
    inbox: InboxRepository
    turns: TurnRepository
    outbox: OutboxRepository
    processor: TurnProcessor
    deliverer: ReplyDeliverer
    dispatcher: TurnDispatcher
    orchestrator: FakeOrchestrator
    sender: FakeSender


def build(
    engine: AsyncEngine, orchestrator: FakeOrchestrator, sender: FakeSender | None = None
) -> Engine:
    sessions = create_session_factory(engine)
    clock = FixedClock(NOW)
    resolved_sender = sender or FakeSender(clock)
    senders: dict[Channel, ChannelSender] = {Channel.WHATSAPP: resolved_sender}
    turns = TurnRepository(sessions)
    outbox = OutboxRepository(sessions)
    processor = TurnProcessor(
        TurnDeps(
            store=turns,
            recorder=DatabaseStepRecorder(TurnStepRepository(sessions)),
            run_turn=orchestrator,
            gate=SafetyGate(),
            senders=senders,
            clock=clock,
        ),
        TurnSettings(
            worker_id="test-worker",
            max_messages=5,
            max_attempts=3,
            stale_after=timedelta(hours=23),
            recent_exchanges=6,
        ),
    )
    deliverer = ReplyDeliverer(
        DeliveryDeps(
            outbox=outbox,
            senders=senders,
            identity=make_identity(),
            retry=RetryPolicy(
                timing=RetryTiming(attempts=1),
                clock=clock,
                sleeper=FakeSleeper(clock),
                rng=random.Random(5),  # noqa: S311  # deterministic jitter for tests
            ),
            clock=clock,
        ),
        DeliverySettings(max_attempts=5, part_budget=timedelta(seconds=25)),
    )
    dispatcher = TurnDispatcher(
        DispatcherDeps(
            processor=processor, deliverer=deliverer, turns=turns, outbox=outbox, clock=clock
        ),
        DispatcherSettings(
            debounce=timedelta(milliseconds=50),
            maintenance_interval=timedelta(hours=1),
            shutdown_grace=timedelta(seconds=1),
            retain_turn_text=timedelta(days=90),
            retain_raw_payload=timedelta(days=7),
            error_backoff=timedelta(seconds=1),
        ),
    )
    return Engine(
        sessions=sessions,
        inbox=InboxRepository(sessions),
        turns=turns,
        outbox=outbox,
        processor=processor,
        deliverer=deliverer,
        dispatcher=dispatcher,
        orchestrator=orchestrator,
        sender=resolved_sender,
    )


def records(*messages: dict[str, JsonValue]) -> list[InboundRecord]:
    identity = make_identity()
    parsed = WhatsAppWebhookParser.parse(
        WebhookBody.model_validate(wa.webhook(list(messages))), TEST_PHONE_NUMBER_ID, identity, NOW
    )
    return [
        InboundRecord(
            message=item.inbound,
            address_ciphertext=identity.encrypt_address(
                item.inbound.user_hash, item.wa_id.get_secret_value()
            ),
            raw_payload=item.raw_payload,
        )
        for item in parsed.messages
    ]


async def store_messages(parts: Engine, *messages: dict[str, JsonValue]) -> UserHash:
    batch = records(*messages)
    await parts.inbox.save(batch)
    return batch[0].message.user_hash


async def scalar(engine: AsyncEngine, sql: str) -> object:
    async with engine.connect() as connection:
        return (await connection.execute(text(sql))).scalar_one()


async def rows(engine: AsyncEngine, sql: str) -> Sequence[tuple[object, ...]]:
    async with engine.connect() as connection:
        return [tuple(row) for row in (await connection.execute(text(sql))).all()]


async def make_everything_due(engine: AsyncEngine) -> None:
    """Stand-in for waiting out a backoff."""
    async with engine.begin() as connection:
        await connection.execute(text("UPDATE inbox_messages SET available_at = now()"))
        await connection.execute(text("UPDATE outbox_messages SET available_at = now()"))


# --- the guarantees ------------------------------------------------------------------------


async def test_one_message_gets_exactly_one_reply(engine: AsyncEngine) -> None:
    parts = build(engine, FakeOrchestrator())
    user = await store_messages(parts, wa.text_message("Munni ne patte ikatthe kiye"))
    parts.dispatcher.wake(user)
    await parts.dispatcher.wait_until_idle()
    assert [sent.part.text for sent in parts.sender.sent] == [ScriptedReply().text]
    assert await rows(engine, "SELECT status FROM turns") == [("completed",)]
    assert await rows(engine, "SELECT status, sending_since FROM outbox_messages") == [
        ("sent", None)
    ]
    assert await rows(engine, "SELECT status FROM inbox_messages") == [("done",)]


async def test_the_same_webhook_three_times_gets_one_reply(engine: AsyncEngine) -> None:
    parts = build(engine, FakeOrchestrator())
    for _ in range(3):
        user = await store_messages(parts, wa.text_message(message_id="wamid.DUP"))
        parts.dispatcher.wake(user)
    await parts.dispatcher.wait_until_idle()
    assert len(parts.sender.sent) == 1
    assert await scalar(engine, "SELECT count(*) FROM turns") == 1


async def test_a_burst_becomes_one_turn(engine: AsyncEngine) -> None:
    parts = build(engine, FakeOrchestrator())
    for number in range(3):
        user = await store_messages(
            parts, wa.text_message(f"sandesh {number}", message_id=f"wamid.B{number}")
        )
        parts.dispatcher.wake(user)
    await parts.dispatcher.wait_until_idle()
    assert [len(context.messages) for context in parts.orchestrator.contexts] == [3]
    assert len(parts.sender.sent) == 1


async def test_a_message_during_a_turn_becomes_the_next_turn(engine: AsyncEngine) -> None:
    gate = asyncio.Event()
    parts = build(engine, FakeOrchestrator(block=gate))
    user = await store_messages(parts, wa.text_message("pehla", message_id="wamid.M1"))
    parts.dispatcher.wake(user)
    await parts.orchestrator.called.wait()
    await store_messages(parts, wa.text_message("doosra", message_id="wamid.M2"))
    parts.dispatcher.wake(user)
    gate.set()
    await parts.dispatcher.wait_until_idle()
    turn_texts = [[m.text for m in context.messages] for context in parts.orchestrator.contexts]
    assert turn_texts == [["pehla"], ["doosra"]]
    assert len(parts.sender.sent) == 2


async def test_a_crashing_pipeline_retries_then_says_try_again_later_once(
    engine: AsyncEngine,
) -> None:
    parts = build(engine, FakeOrchestrator(raise_times=100))
    user = await store_messages(parts, wa.text_message())
    for _ in range(3):
        await parts.processor.process_user_turn(user)
        await make_everything_due(engine)
    assert await rows(engine, "SELECT status, attempts FROM inbox_messages") == [("pending", 3)]
    turn_id = await parts.processor.process_user_turn(user)
    assert turn_id is not None
    await parts.deliverer.deliver_turn(turn_id)
    assert len(parts.orchestrator.contexts) == 3  # the poisoned turn never ran the pipeline
    assert len(parts.sender.sent) == 1
    assert await rows(engine, "SELECT status FROM inbox_messages") == [("failed",)]
    assert await rows(engine, "SELECT status, fixed_reply_kind FROM turns ORDER BY started_at") == [
        ("failed", None)
    ] * 3 + [("completed", "try_again_later")]


async def test_a_turn_left_running_by_a_dead_process_is_answered_once_after_restart(
    engine: AsyncEngine,
) -> None:
    parts = build(engine, FakeOrchestrator())
    user = await store_messages(parts, wa.text_message())
    started = await parts.turns.start_turn(user, max_messages=5, worker_id="dead-process")
    assert started is not None  # the process "died" here, mid-turn
    restarted = build(engine, FakeOrchestrator())
    await restarted.dispatcher.start()
    await restarted.dispatcher.wait_until_idle()
    await restarted.dispatcher.stop()
    assert len(restarted.sender.sent) == 1
    assert await rows(engine, "SELECT worker_id, status FROM turns ORDER BY started_at") == [
        ("dead-process", "failed"),
        ("test-worker", "completed"),
    ]
    assert await rows(engine, "SELECT status, attempts FROM inbox_messages") == [("done", 1)]


async def test_parts_queued_before_a_crash_are_sent_after_restart(engine: AsyncEngine) -> None:
    parts = build(engine, FakeOrchestrator())
    user = await store_messages(parts, wa.text_message())
    await parts.processor.process_user_turn(user)  # finalized, never delivered
    async with engine.begin() as connection:  # one part was mid-send when the process died
        await connection.execute(
            text("UPDATE outbox_messages SET status = 'sending', sending_since = now()")
        )
    restarted = build(engine, FakeOrchestrator())
    await restarted.dispatcher.start()
    await restarted.dispatcher.stop()
    assert len(restarted.sender.sent) == 1
    assert await rows(engine, "SELECT status FROM outbox_messages") == [("sent",)]


async def test_a_retrying_part_holds_back_the_parts_after_it(engine: AsyncEngine) -> None:
    long_reply = ScriptedReply(
        text=("Ek lamba jawab. " * 300).strip(), buttons=(ReplyButton(id="jrn:ok", title="Theek"),)
    )
    clock = FixedClock(NOW)

    def first_send_fails(_part: object, call: int) -> ProviderError | None:
        return ProviderUnavailable("graph api http 503", provider="whatsapp") if call == 1 else None

    parts = build(
        engine, FakeOrchestrator(replies=[long_reply]), FakeSender(clock, first_send_fails)
    )
    user = await store_messages(parts, wa.text_message())
    turn_id = await parts.processor.process_user_turn(user)
    assert turn_id is not None
    await parts.deliverer.deliver_turn(turn_id)
    assert parts.sender.sent == []  # part 0 is waiting to retry; part 1 may not overtake it
    await make_everything_due(engine)
    await parts.deliverer.deliver_turn(turn_id)
    assert [sent.part.part_no for sent in parts.sender.sent] == [0, 1]
    assert parts.sender.sent[-1].part.kind is PartKind.INTERACTIVE


async def test_a_part_that_fails_for_good_does_not_block_the_rest(engine: AsyncEngine) -> None:
    long_reply = ScriptedReply(text=("Ek lamba jawab. " * 300).strip())
    clock = FixedClock(NOW)

    def first_send_rejected(_part: object, call: int) -> ProviderError | None:
        return ProviderRejected("graph api error 100", provider="whatsapp") if call == 1 else None

    parts = build(
        engine, FakeOrchestrator(replies=[long_reply]), FakeSender(clock, first_send_rejected)
    )
    user = await store_messages(parts, wa.text_message())
    turn_id = await parts.processor.process_user_turn(user)
    assert turn_id is not None
    await parts.deliverer.deliver_turn(turn_id)
    assert [sent.part.part_no for sent in parts.sender.sent] == [1]
    assert await rows(engine, "SELECT part_no, status FROM outbox_messages ORDER BY part_no") == [
        (0, "failed"),
        (1, "sent"),
    ]


async def test_a_crisis_turn_keeps_no_user_text(engine: AsyncEngine) -> None:
    crisis = ScriptedReply(route=Route.CRISIS, fixed_kind=FixedReplyKind.CRISIS)
    parts = build(engine, FakeOrchestrator(replies=[crisis]))
    user = await store_messages(parts, wa.text_message("mujhe bahut darr lag raha hai"))
    await parts.processor.process_user_turn(user)
    assert await rows(engine, "SELECT route, user_text, fixed_reply_kind FROM turns") == [
        ("crisis", None, "crisis")
    ]


async def test_recent_exchanges_come_oldest_first_and_sessions_start_after_6h(
    engine: AsyncEngine,
) -> None:
    parts = build(engine, FakeOrchestrator())
    user = await store_messages(parts, wa.text_message("pehla", message_id="wamid.R1"))
    await parts.processor.process_user_turn(user)
    await store_messages(parts, wa.text_message("doosra", message_id="wamid.R2"))
    await parts.processor.process_user_turn(user)
    [first_context, second_context] = parts.orchestrator.contexts
    assert first_context.is_session_start is True
    assert first_context.recent_exchanges == []
    assert [exchange.user_text for exchange in second_context.recent_exchanges] == ["pehla"]


async def test_status_webhooks_only_move_a_part_forward(engine: AsyncEngine) -> None:
    parts = build(engine, FakeOrchestrator())
    user = await store_messages(parts, wa.text_message())
    turn_id = await parts.processor.process_user_turn(user)
    assert turn_id is not None
    await parts.deliverer.deliver_turn(turn_id)
    assert len(parts.sender.sent) == 1
    wamid = "wamid.FAKE1"  # FakeSender's id for its first send
    later = NOW + timedelta(seconds=5)
    assert await parts.outbox.apply_status_update(wamid, OutboxStatus.READ, later, None)
    assert await parts.outbox.apply_status_update(wamid, OutboxStatus.DELIVERED, later, None)
    assert not await parts.outbox.apply_status_update(
        "wamid.NOT_OURS", OutboxStatus.READ, later, None
    )
    [(status, delivered, read)] = await rows(
        engine, "SELECT status, delivered_at IS NOT NULL, read_at IS NOT NULL FROM outbox_messages"
    )
    assert (status, delivered, read) == ("read", True, True)


async def test_deleting_a_user_removes_their_turns_steps_and_outbox(engine: AsyncEngine) -> None:
    parts = build(engine, FakeOrchestrator())
    user = await store_messages(parts, wa.text_message())
    turn_id = await parts.processor.process_user_turn(user)
    assert turn_id is not None
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO turn_steps (turn_id, step, outcome, started_at, duration_ms) "
                "VALUES (:turn, 'route', 'ok', now(), 5)"
            ),
            {"turn": turn_id},
        )
        await connection.execute(text("DELETE FROM users WHERE user_hash = :u"), {"u": user})
    for table in ("turns", "turn_steps", "outbox_messages", "inbox_messages"):
        assert await scalar(engine, f"SELECT count(*) FROM {table}") == 0  # noqa: S608  # test constant


async def test_retention_clears_old_text_and_payloads_only(engine: AsyncEngine) -> None:
    parts = build(engine, FakeOrchestrator())
    user = await store_messages(parts, wa.text_message())
    await parts.processor.process_user_turn(user)
    # The message was received at NOW (test clock); the turn completed at the database's now().
    cleared = await parts.turns.clear_expired_text(
        turn_text_before=NOW - timedelta(days=1), raw_payload_before=NOW - timedelta(days=1)
    )
    assert cleared == 0
    far_future = datetime(2100, 1, 1, tzinfo=UTC)
    cleared = await parts.turns.clear_expired_text(
        turn_text_before=far_future, raw_payload_before=far_future
    )
    assert cleared == 2
    assert await rows(engine, "SELECT user_text, reply_text FROM turns") == [(None, None)]
    assert await rows(engine, "SELECT raw_payload FROM inbox_messages") == [(None,)]


async def test_steps_and_turn_text_are_recorded_as_the_turn_runs(engine: AsyncEngine) -> None:
    parts = build(engine, FakeOrchestrator())
    user = await store_messages(parts, wa.text_message())
    started = await parts.turns.start_turn(user, max_messages=5, worker_id="test-worker")
    assert started is not None
    recorder = DatabaseStepRecorder(TurnStepRepository(parts.sessions))
    await recorder.set_turn_text(started.turn_id, "mujhe doctor banna hai")
    await recorder.set_turn_route(started.turn_id, Route.MENTOR)
    await recorder.record(
        turn_id=started.turn_id,
        step=StepName.GENERATE,
        outcome=StepOutcome.OK,
        started_at=NOW,
        duration_ms=1200,
        usage=StepUsage(
            provider="meta_model_api",
            model="muse-spark-1.3",
            input_tokens=300,
            output_tokens=400,
            audio_seconds=None,
            cost_usd=Decimal("0.002075"),
        ),
        failure=None,
        detail=None,
    )
    assert await rows(engine, "SELECT route, user_text FROM turns") == [
        ("mentor", "mujhe doctor banna hai")
    ]
    assert await rows(engine, "SELECT step, outcome, model, cost_usd FROM turn_steps") == [
        ("generate", "ok", "muse-spark-1.3", Decimal("0.002075"))
    ]


async def test_queued_messages_carry_their_attempts(engine: AsyncEngine) -> None:
    parts = build(engine, FakeOrchestrator())
    user = await store_messages(parts, wa.text_message())
    started = await parts.turns.start_turn(user, max_messages=5, worker_id="w")
    assert started is not None
    [queued] = started.queued
    assert isinstance(queued, QueuedMessage)
    assert queued.attempts == 0
    assert await rows(engine, "SELECT status, turn_id IS NOT NULL FROM inbox_messages") == [
        ("processing", True)
    ]
