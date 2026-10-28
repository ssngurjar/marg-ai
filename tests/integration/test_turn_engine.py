"""The turn engine against real Postgres (s04 §9 integration).

Needs `make test-db-up` and migrations applied (`make test-int` does both). Each test builds the
real stores, leases, processor, deliverer and worker loops around a fake orchestrator and a fake
sender. A test that runs one turn directly takes the user's lease first, as the turn loop does.
"""

import asyncio
import os
import random
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.channels.whatsapp.payloads import WebhookBody
from app.channels.whatsapp.webhook_parser import WhatsAppWebhookParser
from app.core.errors import (
    LeaseLost,
    ProviderError,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.core.types import JsonValue
from app.domain.enums import (
    Channel,
    FixedReplyKind,
    InboxStatus,
    OutboxStatus,
    PartKind,
    Route,
    StepName,
    StepOutcome,
)
from app.domain.models.base import TurnId, UserHash
from app.domain.models.curiosity import CuriositySource, ExtractSignals, UpdateMemory
from app.domain.models.learner import LearnerId
from app.domain.models.reply import ReplyButton
from app.domain.models.turn import QueuedMessage
from app.domain.models.usage import StepUsage
from app.layers.memory_layer import MemoryLayer
from app.providers.http import RetryPolicy, RetryTiming
from app.providers.ports import ChannelSender
from app.safety.safety_gate import SafetyGate
from app.store.db import create_engine, create_listener_engine, create_session_factory
from app.store.notification_listener import ListenerSettings, NotificationListener
from app.store.repositories.aspiration_signal_repository import AspirationSignalRepository
from app.store.repositories.child_session_repository import ChildSessionRepository
from app.store.repositories.curiosity_signal_repository import CuriositySignalRepository
from app.store.repositories.demo_repository import DemoRepository
from app.store.repositories.inbox_repository import InboundRecord, InboxRepository
from app.store.repositories.lease_repository import LeaseRepository, LeaseTimes
from app.store.repositories.media_blob_repository import MediaBlobRepository
from app.store.repositories.outbox_repository import OutboxRepository
from app.store.repositories.profile_memory_repository import ProfileMemoryRepository
from app.store.repositories.turn_repository import FinishedTurn, TurnRepository
from app.store.repositories.turn_step_repository import TurnStepRepository
from app.store.repositories.user_repository import UserRepository
from app.telemetry.aspiration_signal_extractor import AspirationSignalExtractor
from app.telemetry.curiosity_signal_extractor import CuriositySignalExtractor
from app.worker.child_session_summary_sender import ChildSessionSummarySender, SummaryDeps
from app.worker.database_step_recorder import DatabaseStepRecorder
from app.worker.maintenance_loop import MaintenanceDeps, MaintenanceLoop, MaintenanceSettings
from app.worker.outbox_loop import OutboxLoop, OutboxLoopSettings
from app.worker.post_turn_runner import PostTurnDeps, PostTurnRunner
from app.worker.reply_deliverer import DeliveryDeps, DeliverySettings, ReplyDeliverer
from app.worker.supervisor import Supervisor, SupervisorParts
from app.worker.turn_loop import TurnLoop, TurnLoopDeps, TurnLoopSettings
from app.worker.turn_processor import TurnDeps, TurnProcessor, TurnSettings
from tests.fakes.clock import FixedClock
from tests.fakes.domain_policy import rules_only_policy
from tests.fakes.language_model import FakeLanguageModel
from tests.fakes.orchestrator import FakeOrchestrator, ScriptedReply
from tests.fakes.safety_classifier import FakeSafetyClassifier
from tests.fakes.sender import FakeSender
from tests.fakes.sleeper import FakeSleeper
from tests.support import whatsapp_payloads as wa
from tests.support.app_factory import TEST_PHONE_NUMBER_ID, make_identity, make_settings
from tests.support.journey import CURIOSITY_SIGNALS
from tests.support.prompts import shipped_registry

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
    leases: LeaseRepository
    turn_loop: TurnLoop
    maintenance: MaintenanceLoop
    worker: Supervisor
    orchestrator: FakeOrchestrator
    sender: FakeSender


WORKER = "test-worker"
LEASE = timedelta(seconds=60)


@dataclass(frozen=True, slots=True)
class Tuning:
    lease: timedelta = LEASE
    poll_interval: timedelta = timedelta(seconds=2)
    listener_engine: AsyncEngine | None = None  # None: no LISTEN, polling only


def build(
    engine: AsyncEngine,
    orchestrator: FakeOrchestrator,
    sender: FakeSender | None = None,
    tuning: Tuning = Tuning(),  # noqa: B008  # a frozen dataclass, never mutated
) -> Engine:
    lease, poll_interval, listener_engine = (
        tuning.lease,
        tuning.poll_interval,
        tuning.listener_engine,
    )
    sessions = create_session_factory(engine)
    clock = FixedClock(NOW)
    resolved_sender = sender or FakeSender(clock)
    senders: dict[Channel, ChannelSender] = {Channel.WHATSAPP: resolved_sender}
    turns = TurnRepository(sessions)
    outbox = OutboxRepository(sessions)
    leases = LeaseRepository(sessions, LeaseTimes(lease=lease, debounce=timedelta(milliseconds=50)))
    processor = TurnProcessor(
        TurnDeps(
            store=turns,
            recorder=DatabaseStepRecorder(TurnStepRepository(sessions)),
            run_turn=orchestrator,
            gate=SafetyGate(FakeSafetyClassifier(), rules_only_policy()),
            senders=senders,
            clock=clock,
        ),
        TurnSettings(
            worker_id=WORKER,
            max_messages=5,
            max_attempts=3,
            stale_after=timedelta(hours=23),
            recent_exchanges=6,
        ),
    )
    deliverer = ReplyDeliverer(
        DeliveryDeps(
            outbox=outbox,
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
            audio=MediaBlobRepository(sessions),
            images=MediaBlobRepository(sessions),
        ),
        DeliverySettings(max_attempts=5, part_budget=timedelta(seconds=25)),
    )
    turn_loop = TurnLoop(
        TurnLoopDeps(
            processor=processor,
            deliverer=deliverer,
            leases=leases,
            post_turn=PostTurnRunner(
                PostTurnDeps(
                    extractor=CuriositySignalExtractor(
                        FakeLanguageModel([CURIOSITY_SIGNALS]), shipped_registry()
                    ),
                    signals=CuriositySignalRepository(sessions),
                    recorder=DatabaseStepRecorder(TurnStepRepository(sessions)),
                    clock=clock,
                    timeout=timedelta(seconds=5),
                    cards=None,
                    memory=MemoryLayer(FakeLanguageModel([]), shipped_registry()),
                    memories=ProfileMemoryRepository(sessions),
                    aspiration=AspirationSignalExtractor(FakeLanguageModel([]), shipped_registry()),
                    aspirations=AspirationSignalRepository(sessions),
                )
            ),
        ),
        TurnLoopSettings(
            worker_id=WORKER,
            concurrency=4,
            lease=lease,
            poll_interval=poll_interval,
            error_backoff=timedelta(seconds=1),
        ),
    )
    outbox_loop = OutboxLoop(
        outbox,
        deliverer,
        OutboxLoopSettings(
            concurrency=2, poll_interval=poll_interval, error_backoff=timedelta(seconds=1)
        ),
    )
    maintenance = MaintenanceLoop(
        MaintenanceDeps(
            leases=leases,
            outbox=outbox,
            turns=turns,
            users=UserRepository(sessions),
            media=MediaBlobRepository(sessions),
            child_sessions=ChildSessionRepository(sessions),
            demo=DemoRepository(sessions),
            summaries=ChildSessionSummarySender(
                SummaryDeps(
                    sessions=ChildSessionRepository(sessions),
                    gate=SafetyGate(FakeSafetyClassifier(), rules_only_policy()),
                    deliverer=deliverer,
                ),
                WORKER,
            ),
            nudges=None,
            clock=clock,
        ),
        MaintenanceSettings(
            interval=timedelta(hours=1),
            sending_stuck=timedelta(seconds=60),
            retain_turn_text=timedelta(days=90),
            retain_raw_payload=timedelta(days=7),
            purge_sweep_after=timedelta(seconds=600),
            child_session_max=timedelta(minutes=10),
        ),
    )
    listener = (
        NotificationListener(
            listener_engine,
            {
                "inbox_new": lambda _payload: turn_loop.wake.set(),
                "outbox_new": lambda _payload: outbox_loop.wake.set(),
            },
            ListenerSettings(health_check_every=timedelta(seconds=5)),
        )
        if listener_engine is not None
        else None
    )
    worker = Supervisor(
        SupervisorParts(
            turns=turn_loop,
            outbox=outbox_loop,
            maintenance=maintenance,
            listener=listener,
            shutdown_grace=timedelta(seconds=1),
        )
    )
    return Engine(
        sessions=sessions,
        inbox=InboxRepository(sessions),
        turns=turns,
        outbox=outbox,
        processor=processor,
        deliverer=deliverer,
        leases=leases,
        turn_loop=turn_loop,
        maintenance=maintenance,
        worker=worker,
        orchestrator=orchestrator,
        sender=resolved_sender,
    )


async def run_one_turn(parts: Engine, user: UserHash) -> TurnId | None:
    """One turn run directly (as evals do): lease the user, then process."""
    assert await parts.leases.acquire(user, WORKER)
    return await parts.processor.process_user_turn(user)


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


async def expire_leases(engine: AsyncEngine) -> None:
    """Stand-in for a dead worker's lease running out."""
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE users SET lease_expires_at = now() - interval '1 second' "
                "WHERE lease_owner IS NOT NULL"
            )
        )


async def make_everything_due(engine: AsyncEngine) -> None:
    """Stand-in for waiting out a backoff."""
    async with engine.begin() as connection:
        await connection.execute(text("UPDATE inbox_messages SET available_at = now()"))
        await connection.execute(text("UPDATE outbox_messages SET available_at = now()"))


# --- the guarantees ------------------------------------------------------------------------


async def test_one_message_gets_exactly_one_reply(engine: AsyncEngine) -> None:
    parts = build(engine, FakeOrchestrator())
    user = await store_messages(parts, wa.text_message("Munni ne patte ikatthe kiye"))
    parts.worker.wake(user)
    await parts.worker.wait_until_idle()
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
        parts.worker.wake(user)
    await parts.worker.wait_until_idle()
    assert len(parts.sender.sent) == 1
    assert await scalar(engine, "SELECT count(*) FROM turns") == 1


async def test_a_burst_becomes_one_turn(engine: AsyncEngine) -> None:
    parts = build(engine, FakeOrchestrator())
    for number in range(3):
        user = await store_messages(
            parts, wa.text_message(f"sandesh {number}", message_id=f"wamid.B{number}")
        )
        parts.worker.wake(user)
    await parts.worker.wait_until_idle()
    assert [len(context.messages) for context in parts.orchestrator.contexts] == [3]
    assert len(parts.sender.sent) == 1


async def test_a_message_during_a_turn_becomes_the_next_turn(engine: AsyncEngine) -> None:
    gate = asyncio.Event()
    parts = build(engine, FakeOrchestrator(block=gate))
    user = await store_messages(parts, wa.text_message("pehla", message_id="wamid.M1"))
    assert await parts.turn_loop.claim_available() == 1
    await parts.orchestrator.called.wait()
    await store_messages(parts, wa.text_message("doosra", message_id="wamid.M2"))
    parts.worker.wake(user)
    gate.set()
    await parts.worker.wait_until_idle()
    turn_texts = [[m.text for m in context.messages] for context in parts.orchestrator.contexts]
    assert turn_texts == [["pehla"], ["doosra"]]
    assert len(parts.sender.sent) == 2


async def test_a_crashing_pipeline_retries_then_says_try_again_later_once(
    engine: AsyncEngine,
) -> None:
    parts = build(engine, FakeOrchestrator(raise_times=100))
    user = await store_messages(parts, wa.text_message())
    for _ in range(3):
        await run_one_turn(parts, user)
        await make_everything_due(engine)
    assert await rows(engine, "SELECT status, attempts FROM inbox_messages") == [("pending", 3)]
    turn_id = await run_one_turn(parts, user)
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
    assert await parts.leases.acquire(user, "dead-process")
    started = await parts.turns.start_turn(user, max_messages=5, worker_id="dead-process")
    assert started is not None  # the process "died" here, mid-turn
    await expire_leases(engine)
    restarted = build(engine, FakeOrchestrator())
    await restarted.worker.start()  # its first maintenance pass takes the dead turn over
    await make_everything_due(engine)  # stand-in for the takeover's 5 s backoff
    await restarted.worker.wait_until_idle()
    await restarted.worker.stop()
    assert len(restarted.sender.sent) == 1
    assert await rows(engine, "SELECT worker_id, status FROM turns ORDER BY started_at") == [
        ("dead-process", "failed"),
        ("test-worker", "completed"),
    ]
    assert await rows(engine, "SELECT status, attempts FROM inbox_messages") == [("done", 1)]
    assert await rows(engine, "SELECT lease_owner FROM users") == [(None,)]


async def test_parts_queued_before_a_crash_are_sent_after_restart(engine: AsyncEngine) -> None:
    parts = build(engine, FakeOrchestrator())
    user = await store_messages(parts, wa.text_message())
    await run_one_turn(parts, user)  # finalized, never delivered
    async with engine.begin() as connection:  # one part was mid-send when the process died
        await connection.execute(
            text(
                "UPDATE outbox_messages "
                "SET status = 'sending', sending_since = now() - interval '2 minutes'"
            )
        )
    restarted = build(engine, FakeOrchestrator())
    await restarted.worker.start()
    await restarted.worker.wait_until_idle()
    await restarted.worker.stop()
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
    turn_id = await run_one_turn(parts, user)
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
    turn_id = await run_one_turn(parts, user)
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
    await run_one_turn(parts, user)
    assert await rows(engine, "SELECT route, user_text, fixed_reply_kind FROM turns") == [
        ("crisis", None, "crisis")
    ]


async def test_recent_exchanges_come_oldest_first_and_sessions_start_after_6h(
    engine: AsyncEngine,
) -> None:
    parts = build(engine, FakeOrchestrator())
    user = await store_messages(parts, wa.text_message("pehla", message_id="wamid.R1"))
    await run_one_turn(parts, user)
    await store_messages(parts, wa.text_message("doosra", message_id="wamid.R2"))
    await run_one_turn(parts, user)
    [first_context, second_context] = parts.orchestrator.contexts
    assert first_context.is_session_start is True
    assert first_context.recent_exchanges == []
    assert [exchange.user_text for exchange in second_context.recent_exchanges] == ["pehla"]


async def test_status_webhooks_only_move_a_part_forward(engine: AsyncEngine) -> None:
    parts = build(engine, FakeOrchestrator())
    user = await store_messages(parts, wa.text_message())
    turn_id = await run_one_turn(parts, user)
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
    turn_id = await run_one_turn(parts, user)
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
    await run_one_turn(parts, user)
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


# --- several workers (s04 §4.3, §4.8, §4.11) -----------------------------------------------


async def test_two_workers_claim_every_user_exactly_once(engine: AsyncEngine) -> None:
    parts = build(engine, FakeOrchestrator())
    for number in range(20):
        await parts.inbox.save(
            records(
                wa.message(
                    "text",
                    {"text": {"body": f"sandesh {number}"}},
                    wa_id=f"91900000{number + 100:04d}",
                    message_id=f"wamid.U{number}",
                )
            )
        )

    async def claim_all(worker_id: str) -> list[UserHash]:
        claimed: list[UserHash] = []
        while (user := await parts.leases.claim_user(worker_id)) is not None:
            claimed.append(user)
        return claimed

    first, second = await asyncio.gather(claim_all("worker-a"), claim_all("worker-b"))
    assert len(first) + len(second) == 20
    assert len(set(first) | set(second)) == 20  # nobody claimed twice, nobody left out
    owners = await rows(engine, "SELECT lease_owner, count(*) FROM users GROUP BY 1 ORDER BY 1")
    assert sum(int(str(count)) for _, count in owners) == 20


async def test_a_leased_user_is_not_claimed_by_another_worker(engine: AsyncEngine) -> None:
    parts = build(engine, FakeOrchestrator())
    user = await store_messages(parts, wa.text_message())
    assert await parts.leases.acquire(user, "worker-a")
    assert await parts.leases.claim_user("worker-b") is None
    assert not await parts.leases.acquire(user, "worker-b")


async def test_a_user_still_writing_is_not_claimed_inside_the_burst_window(
    engine: AsyncEngine,
) -> None:
    parts = build(engine, FakeOrchestrator())
    user = await store_messages(parts, wa.text_message())
    async with engine.begin() as connection:  # the message arrived just now
        await connection.execute(text("UPDATE inbox_messages SET received_at = now()"))
    patient = LeaseRepository(
        parts.sessions, LeaseTimes(lease=LEASE, debounce=timedelta(seconds=30))
    )
    assert await patient.claim_user(WORKER) is None
    await asyncio.sleep(0.1)  # past the 50 ms window the other repository uses
    assert await parts.leases.claim_user(WORKER) == user


async def test_a_dead_workers_turn_is_taken_over_and_answered_once(engine: AsyncEngine) -> None:
    gate = asyncio.Event()
    dead = build(engine, FakeOrchestrator(block=gate))
    user = await store_messages(dead, wa.text_message())
    stalled = asyncio.create_task(run_one_turn(dead, user))
    await dead.orchestrator.called.wait()  # the worker stalls mid-turn
    await expire_leases(engine)
    await dead.maintenance.run_once()
    assert await rows(engine, "SELECT status, attempts FROM inbox_messages") == [("pending", 1)]
    assert await rows(engine, "SELECT status FROM turns") == [("failed",)]
    gate.set()  # the stalled worker wakes up and tries to finalize: its lease is gone
    await stalled
    assert await scalar(engine, "SELECT count(*) FROM outbox_messages") == 0
    survivor = build(engine, FakeOrchestrator())
    await make_everything_due(engine)
    await survivor.worker.wait_until_idle()
    assert len(dead.sender.sent) + len(survivor.sender.sent) == 1
    assert await rows(engine, "SELECT status FROM turns ORDER BY started_at") == [
        ("failed",),
        ("completed",),
    ]
    assert await rows(engine, "SELECT status, attempts FROM inbox_messages") == [("done", 1)]


async def test_finalize_without_the_lease_writes_nothing(engine: AsyncEngine) -> None:
    parts = build(engine, FakeOrchestrator())
    user = await store_messages(parts, wa.text_message())
    assert await parts.leases.acquire(user, "worker-a")
    started = await parts.turns.start_turn(user, max_messages=5, worker_id="worker-b")
    assert started is not None
    with pytest.raises(LeaseLost, match=user[:8]):
        await parts.turns.finalize(started, FINISHED_FOR_LEASE_TEST, None)
    assert await rows(engine, "SELECT status FROM turns") == [("processing",)]
    assert await rows(engine, "SELECT status FROM inbox_messages") == [("processing",)]
    assert await rows(engine, "SELECT lease_owner FROM users") == [("worker-a",)]


async def test_a_turn_whose_lease_is_taken_is_cancelled_by_its_heartbeat(
    engine: AsyncEngine,
) -> None:
    gate = asyncio.Event()  # never set: only the heartbeat can end this turn
    parts = build(
        engine, FakeOrchestrator(block=gate), tuning=Tuning(lease=timedelta(milliseconds=300))
    )
    await store_messages(parts, wa.text_message())
    assert await parts.turn_loop.claim_available() == 1
    await parts.orchestrator.called.wait()
    async with engine.begin() as connection:  # maintenance gave the user to another worker
        await connection.execute(text("UPDATE users SET lease_owner = 'other-worker'"))
    await asyncio.wait_for(parts.turn_loop.stop(timedelta(seconds=5)), timeout=5)
    assert parts.sender.sent == []
    assert await scalar(engine, "SELECT count(*) FROM outbox_messages") == 0
    assert await rows(engine, "SELECT status FROM turns") == [("failed",)]
    assert await rows(engine, "SELECT lease_owner FROM users") == [("other-worker",)]


async def test_only_parts_stuck_past_the_threshold_are_reset(engine: AsyncEngine) -> None:
    long_reply = ScriptedReply(text=("Ek lamba jawab. " * 300).strip())
    parts = build(engine, FakeOrchestrator(replies=[long_reply]))
    user = await store_messages(parts, wa.text_message())
    await run_one_turn(parts, user)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE outbox_messages SET status = 'sending', sending_since = CASE part_no "
                "WHEN 0 THEN now() - interval '2 minutes' ELSE now() END"
            )
        )
    await parts.maintenance.run_once()
    assert await rows(engine, "SELECT part_no, status FROM outbox_messages ORDER BY part_no") == [
        (0, "pending"),
        (1, "sending"),  # a live worker may be sending it right now
    ]


async def test_a_stored_message_wakes_the_worker_through_notify(
    engine: AsyncEngine, database_url: str
) -> None:
    listen_engine = create_listener_engine(SecretStr(database_url))
    only_notify = Tuning(poll_interval=timedelta(seconds=60), listener_engine=listen_engine)
    parts = build(engine, FakeOrchestrator(), tuning=only_notify)
    await parts.worker.start()
    try:
        await asyncio.sleep(0.2)  # the loops' first pass found nothing
        await store_messages(parts, wa.text_message())  # no wake() call: only the NOTIFY
        for _ in range(100):  # up to 5 s; the poll would take 60
            if parts.sender.sent:
                break
            await asyncio.sleep(0.05)
    finally:
        await parts.worker.stop()
        await listen_engine.dispose()
    assert len(parts.sender.sent) == 1


FINISHED_FOR_LEASE_TEST = FinishedTurn(
    route=None,
    fixed_reply_kind=None,
    user_text=None,
    reply_text=None,
    reply_register=None,
    prompt_versions={},
    failure_step=None,
    failure_kind=None,
    inbox_status=InboxStatus.DONE,
)


async def test_maintenance_prunes_rate_limit_windows_older_than_two_days(
    engine: AsyncEngine,
) -> None:
    parts = build(engine, FakeOrchestrator())
    old, new = f"demo:old:{uuid4().hex}", f"demo:new:{uuid4().hex}"  # the table isn't truncated
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO rate_limit_counters (key, window_start, count) VALUES "
                "(:old, now() - interval '3 days', 5), (:new, now(), 1)"
            ),
            {"old": old, "new": new},
        )
    await parts.maintenance.run_once()
    async with engine.connect() as connection:
        kept = (
            (
                await connection.execute(
                    text("SELECT key FROM rate_limit_counters WHERE key IN (:old, :new)"),
                    {"old": old, "new": new},
                )
            )
            .scalars()
            .all()
        )
    assert kept == [new]


async def test_post_turn_work_that_fails_is_recorded_and_the_next_task_still_runs(
    engine: AsyncEngine,
) -> None:
    """s16 §4.1: signals and memory run after the reply; their failure is a step row only."""
    parts = build(engine, FakeOrchestrator())
    user = await store_messages(parts, wa.text_message())
    turn_id = await run_one_turn(parts, user)
    assert turn_id is not None
    sessions = parts.sessions
    timed_out = ProviderTimeout("muse spark timed out", provider="meta_model_api")
    runner = PostTurnRunner(
        PostTurnDeps(
            extractor=CuriositySignalExtractor(FakeLanguageModel([timed_out]), shipped_registry()),
            signals=CuriositySignalRepository(sessions),
            recorder=DatabaseStepRecorder(TurnStepRepository(sessions)),
            clock=FixedClock(NOW),
            timeout=timedelta(seconds=5),
            cards=None,
            memory=MemoryLayer(FakeLanguageModel([timed_out]), shipped_registry()),
            memories=ProfileMemoryRepository(sessions),
            aspiration=AspirationSignalExtractor(FakeLanguageModel([]), shipped_registry()),
            aspirations=AspirationSignalRepository(sessions),
        )
    )
    signals = ExtractSignals(
        turn_id=turn_id,
        learner_id=LearnerId(uuid4()),
        user_text="Munni ne patte ikatthe kiye",
        source=CuriositySource(
            learner_id=LearnerId(uuid4()), kind="parent_report", hint_domains=[],
            activity_title=None,
        ),
        child_age=5,
    )  # fmt: skip
    memory = UpdateMemory(
        turn_id=turn_id, user_hash=user, previous=None, user_text="x", reply_text="y"
    )
    await runner.run([signals, memory])  # never raises: the reply is already out
    assert await rows(
        engine,
        "SELECT step, outcome, failure_kind FROM turn_steps "
        "WHERE step IN ('extract_signals', 'update_memory') ORDER BY id",
    ) == [("extract_signals", "failed", "timeout"), ("update_memory", "failed", "timeout")]
    assert await rows(engine, "SELECT status FROM turns") == [("completed",)]
    assert await scalar(engine, "SELECT count(*) FROM curiosity_signals") == 0
