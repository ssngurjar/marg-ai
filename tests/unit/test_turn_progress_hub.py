"""TurnProgressHub: each visitor's streams get only their own turns (s14 §4.4)."""

import asyncio
import random
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.api.turn_progress_hub import LATEST, QUEUE_LIMIT, StreamLimits, TurnProgressHub
from app.core.errors import DemoRefused
from app.domain.models.base import UserHash
from app.store.repositories.demo_repository import TurnView
from tests.fakes.demo_turns import FakeDemoTurns

pytestmark = pytest.mark.unit

ASHA = UserHash("a" * 64)
RAVI = UserHash("b" * 64)
LIMITS = StreamLimits(per_visitor=2, per_process=3)


def view(turn_id: UUID) -> TurnView:
    return TurnView(
        turn_id=turn_id, status="processing", route=None, steps=[], parts=[], message_ids=[]
    )


def hub_with(*owned: tuple[UserHash, UUID]) -> tuple[TurnProgressHub, FakeDemoTurns]:
    turns = FakeDemoTurns()
    for owner, turn_id in owned:
        turns.add(owner, view(turn_id))
    return TurnProgressHub(turns, LIMITS), turns


async def settle() -> None:
    """Let the hub's owner lookups (background tasks) finish."""
    for _ in range(5):
        await asyncio.sleep(0)


def queued(subscription_queue: asyncio.Queue[UUID | None]) -> list[UUID | None]:
    items: list[UUID | None] = []
    while not subscription_queue.empty():
        items.append(subscription_queue.get_nowait())
    return items


async def test_a_turn_reaches_its_owners_streams_and_nobody_elses() -> None:
    turn = UUID(int=1)
    hub, _ = hub_with((ASHA, turn))
    asha_tab_1, asha_tab_2, ravi = hub.open(ASHA), hub.open(ASHA), hub.open(RAVI)
    hub.on_notification(str(turn))
    await settle()
    assert queued(asha_tab_1.queue) == [turn]
    assert queued(asha_tab_2.queue) == [turn]
    assert queued(ravi.queue) == []


async def test_the_owner_is_looked_up_once_per_turn() -> None:
    turn = UUID(int=1)
    hub, turns = hub_with((ASHA, turn))
    asha = hub.open(ASHA)
    for _ in range(4):
        hub.on_notification(str(turn))
        await settle()
    assert turns.owner_lookups == [turn]
    assert queued(asha.queue) == [turn] * 4


async def test_with_no_stream_open_nothing_is_looked_up() -> None:
    hub, turns = hub_with((ASHA, UUID(int=1)))
    hub.on_notification(str(UUID(int=1)))
    await settle()
    assert turns.owner_lookups == []


async def test_after_a_reconnect_every_stream_looks_at_its_latest_turn() -> None:
    hub, _ = hub_with()
    asha, ravi = hub.open(ASHA), hub.open(RAVI)
    hub.on_notification("")
    assert queued(asha.queue) == [LATEST]
    assert queued(ravi.queue) == [LATEST]


@pytest.mark.parametrize("payload", ["not-a-uuid", "12345", "' OR 1=1 --"])
async def test_a_payload_that_isnt_a_turn_id_is_dropped(payload: str) -> None:
    hub, turns = hub_with()
    asha = hub.open(ASHA)
    hub.on_notification(payload)
    await settle()
    assert queued(asha.queue) == []
    assert turns.owner_lookups == []


async def test_a_turn_nobody_owns_any_more_is_dropped() -> None:
    hub, _ = hub_with()  # e.g. the visitor pressed reset
    asha = hub.open(ASHA)
    hub.on_notification(str(UUID(int=9)))
    await settle()
    assert queued(asha.queue) == []


async def test_a_failed_owner_lookup_drops_one_update_and_raises_nothing() -> None:
    hub, turns = hub_with((ASHA, UUID(int=1)))
    asha = hub.open(ASHA)
    turns.fail = True
    hub.on_notification(str(UUID(int=1)))
    await settle()
    assert queued(asha.queue) == []


def test_a_third_stream_for_one_visitor_is_refused() -> None:
    hub, _ = hub_with()
    hub.open(ASHA)
    hub.open(ASHA)
    with pytest.raises(DemoRefused, match="stream_limit"):
        hub.open(ASHA)


def test_past_the_process_limit_any_new_stream_is_refused() -> None:
    hub, _ = hub_with()
    hub.open(ASHA)
    hub.open(ASHA)
    hub.open(RAVI)
    with pytest.raises(DemoRefused, match="stream_limit"):
        hub.open(UserHash("c" * 64))


def test_a_closed_stream_frees_its_place() -> None:
    hub, _ = hub_with()
    first = hub.open(ASHA)
    hub.open(ASHA)
    hub.close(first)
    hub.close(first)  # closing twice is harmless
    assert hub.open(ASHA) is not None
    assert hub.open_streams == 2


async def test_a_stream_that_stops_reading_is_marked_to_close() -> None:
    turn = UUID(int=1)
    hub, _ = hub_with((ASHA, turn))
    asha = hub.open(ASHA)
    for _ in range(QUEUE_LIMIT + 1):
        hub.on_notification(str(turn))
        await settle()
    assert asha.overflowed


OWNERS = st.sampled_from([ASHA, RAVI, UserHash("c" * 64)])


@given(
    turns=st.lists(
        st.tuples(OWNERS, st.uuids()), min_size=1, max_size=12, unique_by=lambda t: t[1]
    ),
    order=st.randoms(use_true_random=False),
)
async def test_routing_never_crosses_visitors(
    turns: list[tuple[UserHash, UUID]], order: random.Random
) -> None:
    hub, _ = hub_with(*turns)
    subscriptions = {owner: hub.open(owner) for owner in (ASHA, RAVI)}
    notifications = [turn_id for _, turn_id in turns]
    order.shuffle(notifications)  # any interleaving across visitors
    for turn_id in notifications:
        hub.on_notification(str(turn_id))
    await settle()
    owner_of = {turn_id: owner for owner, turn_id in turns}
    for owner, subscription in subscriptions.items():
        received = queued(subscription.queue)
        assert all(owner_of[turn_id] == owner for turn_id in received if turn_id is not None)
        assert sorted(map(str, received)) == sorted(
            str(turn_id) for turn_id, turn_owner in owner_of.items() if turn_owner == owner
        )
