"""Turn and delivery rules (s04 §4.4, §4.9, §4.10; CLAUDE.md §3 combining and order properties)."""

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.enums import Channel, MessageKind, OutboxStatus
from app.domain.models.base import UserHash
from app.domain.models.delivery import PartState
from app.domain.models.message import InboundMessage
from app.domain.models.turn import QueuedMessage
from app.domain.rules.delivery_planner import DeliveryPlanner
from app.domain.rules.session_rules import SessionRules
from app.domain.rules.turn_batcher import TurnBatcher

pytestmark = pytest.mark.unit

T0 = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
USER = UserHash("a" * 64)


def queued(inbox_id: int, sent_at: datetime, attempts: int = 0) -> QueuedMessage:
    message = InboundMessage(
        channel=Channel.WHATSAPP,
        external_id=f"wamid.{inbox_id}",
        user_hash=USER,
        kind=MessageKind.TEXT,
        text="Munni ne patte ikatthe kiye",
        media=None,
        interactive_reply_id=None,
        provider_sent_at=sent_at,
        received_at=sent_at,
    )
    return QueuedMessage(inbox_id=inbox_id, message=message, attempts=attempts)


@st.composite
def pending_messages(draw: st.DrawFn) -> list[QueuedMessage]:
    """Pending rows in random arrival (id) order with random, possibly equal, send times."""
    offsets = draw(st.lists(st.integers(min_value=0, max_value=50), min_size=0, max_size=12))
    ids = draw(st.permutations(list(range(1, len(offsets) + 1))))
    return [
        queued(inbox_id, T0 + timedelta(seconds=offset))
        for inbox_id, offset in zip(ids, offsets, strict=True)
    ]


# --- combining -----------------------------------------------------------------------------


@given(pending=pending_messages(), cap=st.integers(min_value=1, max_value=8))
def test_batch_is_the_oldest_up_to_the_cap_and_the_rest_wait(
    pending: list[QueuedMessage], cap: int
) -> None:
    batch = TurnBatcher.choose_batch(pending, cap)
    assert len(batch) == min(len(pending), cap)
    keys = [(item.message.provider_sent_at, item.inbox_id) for item in batch]
    assert keys == sorted(keys)
    waiting = [item for item in pending if item not in batch]
    if batch and waiting:
        newest_taken = max(keys)
        assert all(
            (item.message.provider_sent_at, item.inbox_id) > newest_taken for item in waiting
        )


def test_a_late_delivered_older_message_goes_first() -> None:
    late_but_older = queued(9, T0)
    early_but_newer = queued(1, T0 + timedelta(seconds=30))
    assert TurnBatcher.choose_batch([early_but_newer, late_but_older], 5) == [
        late_but_older,
        early_but_newer,
    ]


@pytest.mark.parametrize("cap", [0, -3])
def test_a_cap_below_one_is_rejected(cap: int) -> None:
    with pytest.raises(ValueError, match="max_messages must be at least 1"):
        TurnBatcher.choose_batch([queued(1, T0)], cap)


# --- poison and stale ------------------------------------------------------------------------


@pytest.mark.parametrize("attempts", [(3, 0), (0, 4), (3, 3)])
def test_a_batch_is_poisoned_when_any_message_reached_the_limit(attempts: tuple[int, int]) -> None:
    batch = [queued(1, T0, attempts[0]), queued(2, T0, attempts[1])]
    assert TurnBatcher.is_poisoned(batch, max_attempts=3)


@pytest.mark.parametrize("attempts", [(0, 0), (2, 0), (2, 2)])
def test_a_batch_below_the_limit_is_not_poisoned(attempts: tuple[int, int]) -> None:
    batch = [queued(1, T0, attempts[0]), queued(2, T0, attempts[1])]
    assert not TurnBatcher.is_poisoned(batch, max_attempts=3)


def test_stale_only_when_every_message_is_past_the_window() -> None:
    window = timedelta(hours=23)
    now = T0 + window + timedelta(seconds=1)
    assert TurnBatcher.is_stale([queued(1, T0)], now, window) is True
    assert TurnBatcher.is_stale([queued(1, T0), queued(2, now)], now, window) is False
    assert (
        TurnBatcher.is_stale([queued(1, T0)], T0 + window, window) is False
    )  # exactly at the window
    assert TurnBatcher.is_stale([], now, window) is False


# --- backoff ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("attempts", "seconds"), [(0, 5), (1, 10), (2, 20), (3, 40), (4, 60), (5, 60), (1000, 60)]
)
def test_turn_retry_delay_doubles_from_5s_and_caps_at_60s(attempts: int, seconds: int) -> None:
    assert TurnBatcher.retry_delay(attempts) == timedelta(seconds=seconds)


@pytest.mark.parametrize(
    ("attempts", "seconds"), [(0, 2), (1, 4), (2, 8), (4, 32), (5, 60), (1000, 60)]
)
def test_outbox_retry_delay_doubles_from_2s_and_caps_at_60s(attempts: int, seconds: int) -> None:
    assert DeliveryPlanner.retry_delay(attempts) == timedelta(seconds=seconds)


@pytest.mark.parametrize("delay", [TurnBatcher.retry_delay, DeliveryPlanner.retry_delay])
def test_negative_attempts_are_rejected(delay: object) -> None:
    assert callable(delay)
    with pytest.raises(ValueError, match="attempts can't be negative"):
        delay(-1)


# --- delivery order -------------------------------------------------------------------------

STATUSES = st.sampled_from(list(OutboxStatus))


@given(
    parts=st.lists(st.tuples(STATUSES, st.booleans()), min_size=0, max_size=6).map(
        lambda specs: [
            PartState(part_no=number, status=status, due=due)
            for number, (status, due) in enumerate(specs)
        ]
    )
)
def test_a_part_is_never_sent_past_an_unfinished_earlier_part(parts: list[PartState]) -> None:
    chosen = DeliveryPlanner.next_part_to_send(parts)
    if chosen is None:
        return
    chosen_state = parts[chosen]
    assert chosen_state.status is OutboxStatus.PENDING
    assert chosen_state.due
    earlier = parts[:chosen]
    assert all(part.status not in {OutboxStatus.PENDING, OutboxStatus.SENDING} for part in earlier)


@given(
    outcomes=st.lists(st.sampled_from(["sent", "failed"]), min_size=1, max_size=6),
)
def test_sending_in_turn_finishes_every_part(outcomes: list[str]) -> None:
    """Simulate delivery: each chosen part ends sent or failed; every part ends up finished."""
    parts = [PartState(number, OutboxStatus.PENDING, due=True) for number in range(len(outcomes))]
    for _ in outcomes:
        chosen = DeliveryPlanner.next_part_to_send(parts)
        assert chosen is not None
        final = OutboxStatus.SENT if outcomes[chosen] == "sent" else OutboxStatus.FAILED
        parts[chosen] = PartState(chosen, final, due=True)
    assert DeliveryPlanner.next_part_to_send(parts) is None
    assert {part.status for part in parts} <= {OutboxStatus.SENT, OutboxStatus.FAILED}


def test_a_failed_part_does_not_block_the_next() -> None:
    parts = [
        PartState(0, OutboxStatus.FAILED, due=True),
        PartState(1, OutboxStatus.PENDING, due=True),
    ]
    assert DeliveryPlanner.next_part_to_send(parts) == 1


def test_a_part_waiting_for_its_retry_blocks_the_rest() -> None:
    parts = [
        PartState(0, OutboxStatus.PENDING, due=False),
        PartState(1, OutboxStatus.PENDING, due=True),
    ]
    assert DeliveryPlanner.next_part_to_send(parts) is None


# --- sessions --------------------------------------------------------------------------------


def test_session_start_boundaries() -> None:
    assert SessionRules.is_session_start(None, T0) is True
    assert SessionRules.is_session_start(T0, T0 + SessionRules.SESSION_GAP) is False  # exactly 6 h
    assert (
        SessionRules.is_session_start(T0, T0 + SessionRules.SESSION_GAP + timedelta(seconds=1))
        is True
    )
