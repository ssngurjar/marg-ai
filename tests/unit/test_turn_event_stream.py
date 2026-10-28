"""TurnEventStream: a visitor's turns as SSE text, replay on connect, pings, limits (s14 §4.4)."""

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import timedelta
from uuid import UUID

import pytest

from app.api.turn_event_stream import PING, StreamSettings, TurnEventStream
from app.api.turn_progress_hub import LATEST, StreamLimits, TurnProgressHub
from app.domain.models.base import UserHash
from app.domain.models.reply import ReplyButton
from app.store.repositories.demo_repository import ReplyPartView, TraceStep, TurnView
from tests.fakes.demo_turns import FakeDemoTurns

pytestmark = pytest.mark.unit

ASHA = UserHash("a" * 64)
RAVI = UserHash("b" * 64)
SHORT = StreamSettings(
    max_age=timedelta(seconds=5),
    heartbeat=timedelta(seconds=5),
    replay_window=timedelta(minutes=2),
)


def view(turn_id: UUID, *, done: bool = False, messages: tuple[str, ...] = ("m1",)) -> TurnView:
    return TurnView(
        turn_id=turn_id,
        status="completed" if done else "processing",
        route="journey",
        steps=[TraceStep("safety_in", "ok", 900, None, None, "fake-guard")],
        parts=(
            [
                ReplyPartView(
                    part_no=0,
                    kind="interactive",
                    text="Bahut accha! Munni ne dhyan se dekha.",
                    buttons=[ReplyButton(id="jrn:done", title="Ho gaya")],
                    audio_blob_id=UUID(int=77),
                    image_blob_id=None,
                )
            ]
            if done
            else []
        ),
        message_ids=list(messages),
    )


def setup(
    settings: StreamSettings = SHORT,
) -> tuple[TurnEventStream, TurnProgressHub, FakeDemoTurns]:
    turns = FakeDemoTurns()
    hub = TurnProgressHub(turns, StreamLimits(per_visitor=2, per_process=10))
    return TurnEventStream(hub, turns, settings), hub, turns


def parsed(chunk: str) -> tuple[str, dict[str, object]]:
    name_line, data_line = chunk.strip().split("\n")
    data: dict[str, object] = json.loads(data_line.removeprefix("data: "))
    return name_line.removeprefix("event: "), data


async def next_chunk(events: AsyncGenerator[str]) -> str:
    return await asyncio.wait_for(anext(events), timeout=2)


async def test_it_starts_with_the_reconnect_delay_then_replays_the_latest_turn() -> None:
    stream, hub, turns = setup()
    turns.latest[ASHA] = view(UUID(int=1), done=True)
    events = stream.events(hub.open(ASHA))
    assert await next_chunk(events) == "retry: 2000\n\n"
    name, data = parsed(await next_chunk(events))
    assert name == "turn"
    assert data["replay"] is True
    assert data["turn_id"] == str(UUID(int=1))
    assert data["message_ids"] == ["m1"]
    assert f'"audio_url": "/demo/media/{UUID(int=77)}"' in json.dumps(data["parts"])
    await events.aclose()


async def test_a_queued_turn_is_read_and_sent_whole() -> None:
    stream, hub, turns = setup()
    turns.add(ASHA, view(UUID(int=2)))
    subscription = hub.open(ASHA)
    events = stream.events(subscription)
    await next_chunk(events)  # retry
    subscription.queue.put_nowait(UUID(int=2))
    name, data = parsed(await next_chunk(events))
    assert (name, data["replay"], data["status"]) == ("turn", False, "processing")
    await events.aclose()


async def test_a_burst_of_notifications_for_one_turn_is_one_read() -> None:
    stream, hub, turns = setup()
    turns.add(ASHA, view(UUID(int=2)))
    subscription = hub.open(ASHA)
    events = stream.events(subscription)
    await next_chunk(events)
    for _ in range(5):
        subscription.queue.put_nowait(UUID(int=2))
    await next_chunk(events)
    assert subscription.queue.empty()  # the other four were drained into the same read
    await events.aclose()


async def test_another_visitors_turn_id_sends_nothing() -> None:
    stream, hub, turns = setup()
    turns.add(RAVI, view(UUID(int=3)))
    subscription = hub.open(ASHA)
    events = stream.events(subscription)
    await next_chunk(events)
    subscription.queue.put_nowait(UUID(int=3))  # as if routed wrongly: still not readable
    subscription.queue.put_nowait(LATEST)
    turns.latest[ASHA] = view(UUID(int=4))
    _, data = parsed(await next_chunk(events))
    assert data["turn_id"] == str(UUID(int=4))
    await events.aclose()


async def test_an_idle_stream_sends_pings() -> None:
    quick = StreamSettings(
        max_age=timedelta(seconds=5),
        heartbeat=timedelta(milliseconds=20),
        replay_window=timedelta(minutes=2),
    )
    stream, hub, _ = setup(quick)
    events = stream.events(hub.open(ASHA))
    await next_chunk(events)
    assert await next_chunk(events) == PING
    await events.aclose()


async def test_the_stream_ends_at_its_age_limit_and_frees_its_place() -> None:
    brief = StreamSettings(
        max_age=timedelta(milliseconds=50),
        heartbeat=timedelta(seconds=5),
        replay_window=timedelta(minutes=2),
    )
    stream, hub, _ = setup(brief)
    chunks = [chunk async for chunk in stream.events(hub.open(ASHA))]
    assert chunks == ["retry: 2000\n\n"]
    assert hub.open_streams == 0


async def test_a_database_failure_ends_the_stream_with_an_error_event() -> None:
    stream, hub, turns = setup()
    turns.fail = True
    chunks = [chunk async for chunk in stream.events(hub.open(ASHA))]
    assert parsed(chunks[-1]) == ("error", {"error": "server_busy"})
    assert hub.open_streams == 0


async def test_an_overflowed_stream_closes_so_the_browser_reconnects() -> None:
    stream, hub, _ = setup()
    subscription = hub.open(ASHA)
    subscription.overflowed = True
    chunks = [chunk async for chunk in stream.events(subscription)]
    assert chunks == ["retry: 2000\n\n"]
    assert hub.open_streams == 0


async def test_a_browser_that_goes_away_frees_its_place() -> None:
    stream, hub, _ = setup()
    events = stream.events(hub.open(ASHA))
    await next_chunk(events)
    await events.aclose()  # what Starlette does when the client disconnects
    assert hub.open_streams == 0


async def test_devanagari_reaches_the_page_unescaped() -> None:
    stream, hub, turns = setup()
    hindi = view(UUID(int=5), done=True)
    hindi.parts[0] = ReplyPartView(
        part_no=0, kind="text", text="बहुत अच्छा!", buttons=[], audio_blob_id=None,
        image_blob_id=None,
    )  # fmt: skip
    turns.latest[ASHA] = hindi
    events = stream.events(hub.open(ASHA))
    await next_chunk(events)
    assert "बहुत अच्छा!" in await next_chunk(events)
    await events.aclose()
