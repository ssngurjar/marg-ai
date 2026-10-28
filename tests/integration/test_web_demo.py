"""The web demo against Postgres and the real pipeline (s14): a cookie session, a message in, a
reply and its trace out (polling, and live on the SSE stream), web voice notes, the guards, and
reset."""

import asyncio
import base64
import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.routers import demo
from app.api.turn_event_stream import StreamSettings, TurnEventStream
from app.api.turn_progress_hub import StreamLimits, TurnProgressHub
from app.api.web_demo_ingestor import DemoDeps, DemoLimits, WebDemoIngestor
from app.core.signed_token_codec import SignedTokenCodec
from app.domain.models.base import UserHash
from app.store.db import create_listener_engine, create_session_factory
from app.store.notification_listener import ListenerSettings, NotificationListener
from app.store.repositories.demo_repository import DemoRepository
from app.store.repositories.inbox_repository import InboxRepository
from app.store.repositories.media_blob_repository import MediaBlobRepository
from app.store.repositories.user_repository import UserRepository
from tests.fakes.clock import FixedClock
from tests.fakes.safety_classifier import FakeSafetyClassifier
from tests.fakes.voice import FakeTranscriber, FakeVoice
from tests.integration.test_real_pipeline import NOW, Pipeline, engine, rows, wire
from tests.support.app_factory import make_identity

pytestmark = pytest.mark.integration
__all__ = ["engine"]  # the shared database fixture

ORIGIN = {"origin": "http://demo.test"}
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 64
LIMITS = DemoLimits(
    per_session_per_hour=30,
    per_ip_per_hour=90,
    sessions_per_ip_per_hour=20,
    max_audio_bytes=1_000_000,
    max_image_bytes=1_000_000,
    daily_cost_cap_usd=Decimal(5),
)


LIVE = StreamSettings(
    max_age=timedelta(seconds=2),  # the test client reads a stream only once it has ended
    heartbeat=timedelta(seconds=5),
    replay_window=timedelta(minutes=2),
)


@dataclass(frozen=True, slots=True)
class Demo:
    client: httpx.AsyncClient
    pipeline: Pipeline
    app: FastAPI
    hub: TurnProgressHub


async def demo_for(
    engine: AsyncEngine, limits: DemoLimits = LIMITS, voice: FakeVoice | None = None
) -> AsyncIterator[Demo]:
    pipeline = wire(engine, FakeSafetyClassifier(), voice=voice)
    async with engine.begin() as connection:  # each test starts within every rate limit
        await connection.execute(text("TRUNCATE rate_limit_counters"))
    sessions = create_session_factory(engine)
    app = FastAPI()
    app.include_router(demo.router)
    app.state.web_demo = WebDemoIngestor(
        DemoDeps(
            identity=make_identity(),
            codec=SignedTokenCodec(SecretStr("test-session-signing-key-0123456789")),
            demo=DemoRepository(sessions),
            media=MediaBlobRepository(sessions),
            inbox=InboxRepository(sessions),
            waker=pipeline.worker,
            clock=FixedClock(NOW),
        ),
        limits,
    )
    app.state.media_repository = MediaBlobRepository(sessions)
    app.state.user_repository = UserRepository(sessions)
    hub = TurnProgressHub(DemoRepository(sessions), StreamLimits(per_visitor=2, per_process=10))
    app.state.turn_progress_hub = hub
    app.state.turn_event_stream = TurnEventStream(hub, DemoRepository(sessions), LIVE)
    listen_engine = create_listener_engine(SecretStr(os.environ["DATABASE_URL"]))
    listener = NotificationListener(
        listen_engine,
        {"turn_progress": hub.on_notification},
        ListenerSettings(health_check_every=timedelta(seconds=5)),
    )
    stop = asyncio.Event()
    listening = asyncio.create_task(listener.run(stop))
    await asyncio.wait_for(listener.connected.wait(), timeout=5)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://demo.test") as client:
            yield Demo(client, pipeline, app, hub)
    finally:
        stop.set()
        await listening
        await listen_engine.dispose()


@pytest.fixture
async def site(engine: AsyncEngine) -> AsyncIterator[Demo]:
    async for running in demo_for(engine):
        yield running


async def say(site: Demo, payload: dict[str, str]) -> dict[str, object]:
    """Post a message, let the worker answer, and read what the page would poll."""
    posted = await site.client.post("/demo/messages", json=payload, headers=ORIGIN)
    assert posted.status_code == 202, posted.text
    message_id = posted.json()["message_id"]
    await site.pipeline.worker.wait_until_idle()
    polled = await site.client.get(f"/demo/messages/{message_id}")
    assert polled.status_code == 200
    body: dict[str, object] = polled.json()
    return body


async def test_a_visitor_gets_a_cookie_and_onboarding_with_a_trace(site: Demo) -> None:
    session = await site.client.get("/demo/session")
    assert session.status_code == 200
    assert "marg_session" in session.cookies
    assert session.headers["x-content-type-options"] == "nosniff"
    view = await say(site, {"text": "Hi"})
    turn = view["turn"]
    assert isinstance(turn, dict)
    assert turn["route"] == "onboarding"
    assert any(step["step"] == "route" for step in turn["steps"])
    [first] = turn["parts"]
    assert "consent" in str(first["buttons"]).lower() or first["buttons"]


async def test_the_trace_names_the_model_behind_each_step(site: Demo) -> None:
    await site.client.get("/demo/session")
    view = await say(site, {"text": "Hi"})
    turn = view["turn"]
    assert isinstance(turn, dict)
    models = {step["step"]: step["model"] for step in turn["steps"]}
    assert models["route"] is None  # deterministic: no model
    assert models["safety_in"] == "fake-guard+muse-spark-1.3"  # Llama Guard and the policy check


async def test_the_page_is_served_with_its_security_headers(site: Demo) -> None:
    page = await site.client.get("/demo")
    assert page.status_code == 200
    assert "Marg.ai" in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]


async def test_without_a_cookie_messages_are_refused(site: Demo) -> None:
    response = await site.client.post("/demo/messages", json={"text": "Hi"}, headers=ORIGIN)
    assert (response.status_code, response.json()) == (401, {"error": "no_session"})


async def test_a_post_from_another_site_is_refused(site: Demo) -> None:
    await site.client.get("/demo/session")
    response = await site.client.post(
        "/demo/messages", json={"text": "Hi"}, headers={"origin": "https://evil.example"}
    )
    assert (response.status_code, response.json()) == (403, {"error": "bad_origin"})
    missing = await site.client.post("/demo/messages", json={"text": "Hi"})
    assert missing.status_code == 403


async def test_a_forged_button_is_refused_and_nothing_is_stored(
    site: Demo, engine: AsyncEngine
) -> None:
    await site.client.get("/demo/session")
    response = await site.client.post(
        "/demo/messages", json={"button_id": "onb:delete:yes"}, headers=ORIGIN
    )
    assert response.status_code == 422
    assert response.json() == {
        "error": "invalid_message",
        "field": "button_id",
        "reason": "unknown_button",
    }
    assert await rows(engine, "SELECT count(*) FROM inbox_messages") == [(0,)]


async def test_a_mislabelled_voice_note_is_refused(site: Demo) -> None:
    await site.client.get("/demo/session")
    fake = base64.b64encode(b"MZ an exe").decode("ascii")
    response = await site.client.post(
        "/demo/messages", json={"audio_base64": fake, "audio_type": "audio/webm"}, headers=ORIGIN
    )
    assert response.json()["reason"] == "type_mismatch"


async def test_a_web_voice_note_is_heard_answered_and_then_deleted(engine: AsyncEngine) -> None:
    voice = FakeVoice(transcriber=FakeTranscriber(["Hi"]))
    async for site in demo_for(engine, voice=voice):
        await site.client.get("/demo/session")
        encoded = base64.b64encode(WEBM).decode("ascii")
        view = await say(site, {"audio_base64": encoded, "audio_type": "audio/webm"})
        turn = view["turn"]
        assert isinstance(turn, dict)
        steps = [step["step"] for step in turn["steps"]]
        assert steps[:2] == ["fetch_media", "transcribe"]
        assert voice.transcriber.hints  # the stored note reached speech-to-text
    assert await rows(
        engine, "SELECT count(*) FROM media_blobs WHERE purpose = 'inbound_audio'"
    ) == [(0,)]


async def test_a_web_photo_is_answered_and_then_deleted(site: Demo, engine: AsyncEngine) -> None:
    await site.client.get("/demo/session")
    encoded = base64.b64encode(b"\xff\xd8\xff\xe0 a photo of stones").decode("ascii")
    view = await say(site, {"image_base64": encoded, "image_type": "image/jpeg"})
    turn = view["turn"]
    assert isinstance(turn, dict)
    assert turn["status"] != "processing"  # answered (a new visitor is asked for consent first)
    assert await rows(
        engine, "SELECT count(*) FROM media_blobs WHERE purpose = 'inbound_photo'"
    ) == [(0,)]


async def test_a_mislabelled_photo_is_refused_and_nothing_is_stored(
    site: Demo, engine: AsyncEngine
) -> None:
    await site.client.get("/demo/session")
    fake = base64.b64encode(b"<svg onload=alert(1)>").decode("ascii")
    response = await site.client.post(
        "/demo/messages", json={"image_base64": fake, "image_type": "image/png"}, headers=ORIGIN
    )
    assert response.status_code == 422
    assert response.json() == {
        "error": "invalid_message",
        "field": "image",
        "reason": "type_mismatch",
    }
    assert await rows(engine, "SELECT count(*) FROM media_blobs") == [(0,)]


async def test_a_photo_that_isnt_base64_is_refused(site: Demo) -> None:
    await site.client.get("/demo/session")
    response = await site.client.post(
        "/demo/messages",
        json={"image_base64": "not base64!!", "image_type": "image/jpeg"},
        headers=ORIGIN,
    )
    assert response.status_code == 422
    assert response.json()["field"] == "image"


async def test_over_the_hourly_limit_is_429_and_counts_nothing(engine: AsyncEngine) -> None:
    tight = DemoLimits(
        per_session_per_hour=1,
        per_ip_per_hour=90,
        sessions_per_ip_per_hour=20,
        max_audio_bytes=1_000_000,
        max_image_bytes=1_000_000,
        daily_cost_cap_usd=Decimal(5),
    )
    async for site in demo_for(engine, limits=tight):
        await site.client.get("/demo/session")
        await say(site, {"text": "Hi"})
        response = await site.client.post("/demo/messages", json={"text": "Hi"}, headers=ORIGIN)
        assert response.status_code == 429
        assert response.json()["scope"] == "session"
        assert int(response.headers["retry-after"]) > 0


async def test_past_the_daily_budget_the_demo_rests(engine: AsyncEngine) -> None:
    broke = DemoLimits(
        per_session_per_hour=30,
        per_ip_per_hour=90,
        sessions_per_ip_per_hour=20,
        max_audio_bytes=1_000_000,
        max_image_bytes=1_000_000,
        daily_cost_cap_usd=Decimal(0),
    )
    async for site in demo_for(engine, limits=broke):
        await site.client.get("/demo/session")
        response = await site.client.post("/demo/messages", json={"text": "Hi"}, headers=ORIGIN)
        assert (response.status_code, response.json()["error"]) == (503, "daily_budget_reached")


async def test_someone_elses_message_and_media_are_not_found(
    site: Demo, engine: AsyncEngine
) -> None:
    await site.client.get("/demo/session")
    posted = await site.client.post("/demo/messages", json={"text": "Hi"}, headers=ORIGIN)
    message_id = posted.json()["message_id"]
    await site.pipeline.worker.wait_until_idle()
    site.client.cookies.clear()
    await site.client.get("/demo/session")  # a different visitor
    assert (await site.client.get(f"/demo/messages/{message_id}")).status_code == 404
    blob = (await rows(engine, "SELECT gen_random_uuid()"))[0][0]
    assert (await site.client.get(f"/demo/media/{blob}")).status_code == 404


async def test_reset_deletes_everything_and_the_cookie(site: Demo, engine: AsyncEngine) -> None:
    await site.client.get("/demo/session")
    await say(site, {"text": "Hi"})
    response = await site.client.post("/demo/reset", headers=ORIGIN)
    assert response.status_code == 204
    assert await rows(engine, "SELECT count(*) FROM users WHERE channel = 'web'") == [(0,)]
    assert "marg_session" not in site.client.cookies


# --- the live trace (s14 §4.4, E2 upgrade) ---------------------------------------------------


def turn_events(stream_text: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for block in stream_text.split("\n\n"):
        lines = block.strip().split("\n")
        if lines[0] == "event: turn":
            event: dict[str, object] = json.loads(lines[1].removeprefix("data: "))
            events.append(event)
    return events


async def stream_opened(hub: TurnProgressHub, count: int = 1) -> None:
    for _ in range(100):
        if hub.open_streams >= count:
            return
        await asyncio.sleep(0.01)
    pytest.fail("the stream never opened")


async def test_the_live_stream_carries_each_step_and_then_the_reply(site: Demo) -> None:
    await site.client.get("/demo/session")

    async def talk() -> str:
        await stream_opened(site.hub)
        posted = await site.client.post("/demo/messages", json={"text": "Hi"}, headers=ORIGIN)
        await site.pipeline.worker.wait_until_idle()
        message_id: str = posted.json()["message_id"]
        return message_id

    watched, message_id = await asyncio.gather(site.client.get("/demo/events"), talk())
    assert watched.status_code == 200
    assert watched.headers["content-type"].startswith("text/event-stream")
    assert watched.headers["x-accel-buffering"] == "no"
    assert watched.text.startswith("retry: 2000")
    events = turn_events(watched.text)
    assert len(events) > 1  # the trace grew step by step, not once at the end
    assert all(event["replay"] is False for event in events)
    assert {event["turn_id"] for event in events} == {events[-1]["turn_id"]}
    last = events[-1]
    assert last["message_ids"] == [message_id]
    assert last["status"] == "completed"
    assert last["parts"]
    step_counts: list[int] = []
    for event in events:
        steps = event["steps"]
        assert isinstance(steps, list)
        step_counts.append(len(steps))
    assert step_counts == sorted(step_counts)
    assert site.hub.open_streams == 0  # the stream closed at its age limit and let go


async def test_a_reconnecting_page_gets_the_latest_turn_replayed(site: Demo) -> None:
    await site.client.get("/demo/session")
    await say(site, {"text": "Hi"})
    watched = await site.client.get("/demo/events")
    [replayed] = turn_events(watched.text)
    assert replayed["replay"] is True
    assert replayed["status"] == "completed"


async def test_each_visitor_sees_only_their_own_turns(site: Demo) -> None:
    transport = httpx.ASGITransport(app=site.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://demo.test") as other:
        await other.get("/demo/session")
        await site.client.get("/demo/session")

        async def other_visitor_talks() -> None:
            await stream_opened(site.hub)
            await other.post("/demo/messages", json={"text": "Hi"}, headers=ORIGIN)
            await site.pipeline.worker.wait_until_idle()

        watched, _ = await asyncio.gather(site.client.get("/demo/events"), other_visitor_talks())
    assert watched.status_code == 200
    assert turn_events(watched.text) == []


async def test_the_live_stream_needs_a_session(site: Demo) -> None:
    response = await site.client.get("/demo/events")
    assert (response.status_code, response.json()) == (401, {"error": "no_session"})
    assert site.hub.open_streams == 0


async def test_a_third_stream_for_one_visitor_is_refused(site: Demo, engine: AsyncEngine) -> None:
    await site.client.get("/demo/session")
    [(visitor,)] = await rows(engine, "SELECT user_hash FROM users WHERE channel = 'web'")
    site.hub.open(UserHash(str(visitor)))
    site.hub.open(UserHash(str(visitor)))  # two tabs already open
    response = await site.client.get("/demo/events")
    assert (response.status_code, response.json()) == (
        429,
        {"error": "stream_limit", "scope": "streams"},
    )
