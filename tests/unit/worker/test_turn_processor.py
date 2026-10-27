"""process_user_turn (s04 §4.4 to §4.9) against an in-memory turn store."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.errors import ProviderUnavailable
from app.domain.enums import (
    Channel,
    ConversationState,
    FailureKind,
    FixedReplyKind,
    InboxStatus,
    MessageKind,
    PartKind,
    Route,
    StepName,
)
from app.domain.models.base import TurnId, UserHash
from app.domain.models.message import InboundMessage
from app.domain.models.turn import QueuedMessage, TurnContext, UserProfile
from app.domain.rules.turn_batcher import TurnBatcher
from app.pipeline.reply_parts_builder import ReplyDelivery
from app.pipeline.step_models import StepFailure
from app.providers.ports import ChannelSender
from app.safety.safety_gate import SafetyGate
from app.store.repositories.turn_repository import (
    FinalizeResult,
    FinishedTurn,
    StartedTurn,
    TurnRepository,
)
from app.worker.turn_processor import TurnDeps, TurnProcessor, TurnSettings
from tests.fakes.clock import FixedClock
from tests.fakes.orchestrator import FakeOrchestrator, ScriptedReply
from tests.fakes.safety_classifier import FakeSafetyClassifier
from tests.fakes.sender import FakeSender

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
USER = UserHash("b" * 64)
SETTINGS = TurnSettings(
    worker_id="test-worker",
    max_messages=5,
    max_attempts=3,
    stale_after=timedelta(hours=23),
    recent_exchanges=6,
)


@dataclass(frozen=True, slots=True)
class Finalized:
    finished: FinishedTurn
    delivery: ReplyDelivery | None


@dataclass(frozen=True, slots=True)
class Abandoned:
    count_attempt: bool
    retry_after: timedelta


class MemoryTurnStore(TurnRepository):
    """Hands out one scripted batch, then records what the processor does with it."""

    def __init__(self, batch: list[QueuedMessage]) -> None:
        self.batch = batch
        self.finalized: list[Finalized] = []
        self.abandoned: list[Abandoned] = []
        self.turn_id = TurnId(uuid4())

    async def start_turn(
        self, user_hash: UserHash, max_messages: int, worker_id: str
    ) -> StartedTurn | None:
        if not self.batch:
            return None
        return StartedTurn(
            turn_id=self.turn_id, user_hash=user_hash, channel=Channel.WHATSAPP, queued=self.batch
        )

    async def load_context(self, started: StartedTurn, recent_exchanges: int) -> TurnContext:
        return TurnContext(
            turn_id=started.turn_id,
            profile=UserProfile(
                user_hash=started.user_hash,
                channel=Channel.WHATSAPP,
                state=ConversationState.ACTIVE,
                last_inbound_at=NOW,
            ),
            messages=[queued.message for queued in started.queued],
            recent_exchanges=[],
            is_session_start=True,
        )

    async def finalize(
        self, started: StartedTurn, finished: FinishedTurn, delivery: ReplyDelivery | None
    ) -> FinalizeResult:
        self.finalized.append(Finalized(finished, delivery))
        return FinalizeResult(
            parts_enqueued=len(delivery.parts) if delivery else 0, more_pending=False
        )

    async def abandon(
        self, started: StartedTurn, *, count_attempt: bool, retry_after: timedelta
    ) -> None:
        self.abandoned.append(Abandoned(count_attempt, retry_after))


def message(
    number: int, *, sent_at: datetime = NOW, text: str = "Munni ne patte ikatthe kiye"
) -> InboundMessage:
    return InboundMessage(
        channel=Channel.WHATSAPP,
        external_id=f"wamid.IN{number}",
        user_hash=USER,
        kind=MessageKind.TEXT,
        text=text,
        media=None,
        interactive_reply_id=None,
        provider_sent_at=sent_at,
        received_at=sent_at,
    )


def processor(
    store: MemoryTurnStore, orchestrator: FakeOrchestrator, sender: FakeSender
) -> TurnProcessor:
    senders: dict[Channel, ChannelSender] = {Channel.WHATSAPP: sender}
    deps = TurnDeps(
        store=store,
        recorder=_NoRecorder(),
        run_turn=orchestrator,
        gate=SafetyGate(FakeSafetyClassifier()),
        senders=senders,
        clock=FixedClock(NOW),
    )
    return TurnProcessor(deps, SETTINGS)


class _NoRecorder:
    async def record(self, **_: object) -> None:
        return None

    async def set_turn_text(self, turn_id: TurnId, user_text: str) -> None:
        return None

    async def set_turn_route(self, turn_id: TurnId, route: Route) -> None:
        return None


async def test_a_turn_acknowledges_the_newest_message_runs_and_finalizes() -> None:
    batch = [QueuedMessage(1, message(1), 0), QueuedMessage(2, message(2), 0)]
    store = MemoryTurnStore(batch)
    orchestrator = FakeOrchestrator()
    sender = FakeSender(FixedClock(NOW))
    turn_id = await processor(store, orchestrator, sender).process_user_turn(USER)
    assert turn_id == store.turn_id
    assert sender.acknowledged == ["wamid.IN2"]
    assert [context.messages for context in orchestrator.contexts] == [[message(1), message(2)]]
    [finalized] = store.finalized
    assert finalized.finished.inbox_status is InboxStatus.DONE
    assert finalized.finished.route is Route.JOURNEY
    assert finalized.delivery is not None
    assert [part.kind for part in finalized.delivery.parts] == [PartKind.TEXT]


async def test_nothing_due_returns_none_without_running() -> None:
    orchestrator = FakeOrchestrator()
    turn_id = await processor(
        MemoryTurnStore([]), orchestrator, FakeSender(FixedClock(NOW))
    ).process_user_turn(USER)
    assert turn_id is None
    assert orchestrator.contexts == []


async def test_a_failed_acknowledge_does_not_stop_the_turn() -> None:
    store = MemoryTurnStore([QueuedMessage(1, message(1), 0)])
    sender = FakeSender(
        FixedClock(NOW),
        acknowledge_error=ProviderUnavailable("graph api http 503", provider="whatsapp"),
    )
    await processor(store, FakeOrchestrator(), sender).process_user_turn(USER)
    assert len(store.finalized) == 1


async def test_a_step_failure_still_completes_the_turn_and_records_it() -> None:
    failure = StepFailure(
        step=StepName.GENERATE, kind=FailureKind.TIMEOUT, detail="timeout", retryable=True
    )
    store = MemoryTurnStore([QueuedMessage(1, message(1), 0)])
    orchestrator = FakeOrchestrator(replies=[ScriptedReply(first_failure=failure)])
    await processor(store, orchestrator, FakeSender(FixedClock(NOW))).process_user_turn(USER)
    [finalized] = store.finalized
    assert finalized.finished.failure_step is StepName.GENERATE
    assert finalized.finished.failure_kind is FailureKind.TIMEOUT
    assert finalized.finished.inbox_status is InboxStatus.DONE


async def test_a_crashing_pipeline_puts_the_messages_back_with_backoff() -> None:
    store = MemoryTurnStore([QueuedMessage(1, message(1), 1)])
    orchestrator = FakeOrchestrator(raise_times=1)
    await processor(store, orchestrator, FakeSender(FixedClock(NOW))).process_user_turn(USER)
    assert store.finalized == []
    assert store.abandoned == [
        Abandoned(count_attempt=True, retry_after=TurnBatcher.retry_delay(1))
    ]


async def test_a_poisoned_batch_gets_try_again_later_once_without_running() -> None:
    store = MemoryTurnStore([QueuedMessage(1, message(1), 3)])
    orchestrator = FakeOrchestrator()
    sender = FakeSender(FixedClock(NOW))
    await processor(store, orchestrator, sender).process_user_turn(USER)
    assert orchestrator.contexts == []
    assert sender.acknowledged == []
    [finalized] = store.finalized
    assert finalized.finished.fixed_reply_kind is FixedReplyKind.TRY_AGAIN_LATER
    assert finalized.finished.inbox_status is InboxStatus.FAILED
    assert finalized.delivery is not None
    assert len(finalized.delivery.parts) == 1


async def test_a_stale_batch_is_closed_without_a_reply() -> None:
    old = message(1, sent_at=NOW - timedelta(hours=24))
    store = MemoryTurnStore([QueuedMessage(1, old, 0)])
    orchestrator = FakeOrchestrator()
    await processor(store, orchestrator, FakeSender(FixedClock(NOW))).process_user_turn(USER)
    assert orchestrator.contexts == []
    [finalized] = store.finalized
    assert finalized.delivery is None
    assert finalized.finished.inbox_status is InboxStatus.DONE


async def test_a_crisis_outcome_passes_its_kind_so_finalize_drops_the_text() -> None:
    store = MemoryTurnStore([QueuedMessage(1, message(1, text="mujhe darr lag raha hai"), 0)])
    orchestrator = FakeOrchestrator(
        replies=[ScriptedReply(route=Route.CRISIS, fixed_kind=FixedReplyKind.CRISIS)]
    )
    await processor(store, orchestrator, FakeSender(FixedClock(NOW))).process_user_turn(USER)
    [finalized] = store.finalized
    assert finalized.finished.fixed_reply_kind is FixedReplyKind.CRISIS


async def test_shutdown_mid_turn_requeues_without_counting_an_attempt() -> None:
    store = MemoryTurnStore([QueuedMessage(1, message(1), 0)])
    orchestrator = FakeOrchestrator(block=asyncio.Event())
    task = asyncio.create_task(
        processor(store, orchestrator, FakeSender(FixedClock(NOW))).process_user_turn(USER)
    )
    await orchestrator.called.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.abandoned == [Abandoned(count_attempt=False, retry_after=timedelta(0))]
    assert store.finalized == []
