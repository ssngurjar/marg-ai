"""TelemetryRepository against Postgres: the turn_metrics view, the step percentiles, today's
cost on the India day boundary, and the young learners' data (s13 §4.1, §4.6)."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.clock import SystemClock
from app.domain.enums import Channel, ChildSessionEndReason, CuriosityDomain
from app.domain.models.learner import LearnerId
from app.store.db import create_engine, create_session_factory
from app.store.repositories.telemetry_repository import ActivityCounts, TelemetryRepository
from tests.support.app_factory import make_settings

pytestmark = pytest.mark.integration

PARENT = "a" * 64
WEB_VISITOR = "b" * 64
MUNNI = UUID(int=11)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL must point at the docker-compose.test.yml database")
    engine = create_engine(make_settings(database_url=url))
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE users, inbox_messages RESTART IDENTITY CASCADE"))
        for user_hash, channel in ((PARENT, "whatsapp"), (WEB_VISITOR, "web")):
            await connection.execute(
                text("INSERT INTO users (user_hash, channel, state) VALUES (:h, :c, 'active')"),
                {"h": user_hash, "c": channel},
            )
    yield engine
    await engine.dispose()


@pytest.fixture
def telemetry(engine: AsyncEngine) -> TelemetryRepository:
    return TelemetryRepository(create_session_factory(engine))


async def sql(engine: AsyncEngine, statement: str, **values: object) -> None:
    async with engine.begin() as connection:
        await connection.execute(text(statement), values)


async def turn(  # noqa: PLR0913  # one keyword per turns column a test sets
    engine: AsyncEngine,
    *,
    user_hash: str = PARENT,
    route: str = "journey",
    fixed_reply_kind: str | None = None,
    received_seconds_ago: float | None = 30,
    reply_after_s: float | None = 4.0,
    status: str = "completed",
) -> UUID:
    """A turn, with its inbound message and first sent part `reply_after_s` after it arrived."""
    turn_id = uuid4()
    await sql(
        engine,
        "INSERT INTO turns (id, user_hash, status, route, fixed_reply_kind, worker_id, started_at)"
        " VALUES (:id, :h, :s, :r, :f, 'test', now() - interval '1 minute')",
        id=turn_id, h=user_hash, s=status, r=route, f=fixed_reply_kind,
    )  # fmt: skip
    if received_seconds_ago is not None:
        await sql(
            engine,
            "INSERT INTO inbox_messages (channel, external_id, user_hash, kind, text, turn_id,"
            " status, provider_sent_at, received_at)"
            " VALUES ('whatsapp', :e, :h, 'text', 'x', :t, 'done', now(),"
            " now() - make_interval(secs => :ago))",
            e=str(uuid4()), h=user_hash, t=turn_id, ago=received_seconds_ago,
        )  # fmt: skip
        if reply_after_s is not None:
            await sql(
                engine,
                "INSERT INTO outbox_messages (turn_id, part_no, user_hash, channel, kind, text,"
                " status, sent_at)"
                " VALUES (:t, 0, :h, 'whatsapp', 'text', 'reply', 'sent',"
                " now() - make_interval(secs => :ago) + make_interval(secs => :after))",
                t=turn_id, h=user_hash, ago=received_seconds_ago, after=reply_after_s,
            )  # fmt: skip
    return turn_id


async def step(  # noqa: PLR0913  # one keyword per turn_steps column a test sets
    engine: AsyncEngine,
    turn_id: UUID,
    name: str,
    duration_ms: int,
    *,
    outcome: str = "ok",
    detail: str | None = None,
    cost: str = "0",
    started_at: datetime | None = None,
) -> None:
    await sql(
        engine,
        "INSERT INTO turn_steps (turn_id, step, outcome, detail, cost_usd, started_at,"
        " duration_ms) VALUES (:t, :s, :o, :d, :c, COALESCE(:at, now()), :ms)",
        t=turn_id, s=name, o=outcome, d=detail, c=Decimal(cost), at=started_at, ms=duration_ms,
    )  # fmt: skip


# --- the turn_metrics view ------------------------------------------------------------------------


async def test_user_latency_runs_from_arrival_to_the_first_part_sent(
    engine: AsyncEngine, telemetry: TelemetryRepository
) -> None:
    await turn(engine, reply_after_s=4.0)
    await turn(engine, reply_after_s=8.0)
    summary = await telemetry.turn_summary_24h()
    assert summary.turns == 2
    assert summary.p50_user_ms == pytest.approx(6000, abs=5)
    assert summary.p95_user_ms == pytest.approx(7800, abs=5)


async def test_nudges_have_no_latency_and_holding_replies_arent_served_ok(
    engine: AsyncEngine, telemetry: TelemetryRepository
) -> None:
    await turn(engine, reply_after_s=5.0)
    await turn(engine, route="nudge", received_seconds_ago=None)
    await turn(engine, fixed_reply_kind="holding")
    await turn(engine, fixed_reply_kind="crisis", route="crisis")
    summary = await telemetry.turn_summary_24h()
    assert summary.turns == 4
    assert summary.nudges_sent == 1
    assert summary.crisis_turns == 1
    assert summary.served_ok_rate == pytest.approx(0.75)  # the crisis reply was served well
    assert summary.p50_user_ms == pytest.approx(4000, abs=5)  # the nudge is left out


async def test_with_no_turns_the_summary_is_empty_not_an_error(
    telemetry: TelemetryRepository,
) -> None:
    summary = await telemetry.turn_summary_24h()
    assert (summary.turns, summary.served_ok_rate, summary.p50_user_ms) == (0, None, None)


# --- steps, journey counts, failures, cost -------------------------------------------------------


async def test_step_percentiles_and_rates_skip_skipped_rows(
    engine: AsyncEngine, telemetry: TelemetryRepository
) -> None:
    turn_id = await turn(engine)
    for duration in (100, 200, 300, 400):
        await step(engine, turn_id, "generate", duration)
    await step(engine, turn_id, "generate", 999, outcome="degraded")
    await step(engine, turn_id, "translate", 0, outcome="skipped")
    two_days_ago = SystemClock().now() - timedelta(days=2)
    await step(engine, turn_id, "generate", 50, started_at=two_days_ago)
    [generate] = await telemetry.step_latency_24h()
    assert (generate.step, generate.runs) == ("generate", 5)
    assert generate.p50_ms == 300
    assert generate.ok_rate == 1.0
    assert generate.degraded_rate == pytest.approx(0.2)


async def test_journey_counts_photos_refusals_and_cards(
    engine: AsyncEngine, telemetry: TelemetryRepository
) -> None:
    turn_id = await turn(engine, fixed_reply_kind="photo_has_person")
    await step(engine, turn_id, "analyze_image", 1800, detail="person_check=reject")
    other = await turn(engine)
    await step(engine, other, "analyze_image", 1700, detail="person_check=pass")
    await step(engine, other, "analyze_image", 1900, detail="stone=5")
    await step(engine, other, "make_card", 18000, detail="sent")
    await step(engine, other, "make_card", 100, outcome="skipped", detail="low_engagement")
    counts = await telemetry.journey_counts_24h()
    assert (counts.photos_received, counts.photos_refused, counts.cards_sent) == (2, 1, 1)


async def test_failures_are_counted_per_step_and_kind(
    engine: AsyncEngine, telemetry: TelemetryRepository
) -> None:
    turn_id = await turn(engine)
    await sql(
        engine,
        "INSERT INTO turn_steps (turn_id, step, outcome, failure_kind, started_at, duration_ms)"
        " VALUES (:t, 'safety_in', 'failed', 'timeout', now(), 1500),"
        " (:t, 'safety_in', 'failed', 'timeout', now(), 1500)",
        t=turn_id,
    )
    [failure] = await telemetry.failures_24h()
    assert (failure.step, failure.failure_kind, failure.turns) == (
        "safety_in",
        "timeout",
        2,
    )


async def test_todays_cost_starts_at_india_midnight_and_filters_by_channel(
    engine: AsyncEngine, telemetry: TelemetryRepository
) -> None:
    india_midnight = datetime(2026, 10, 28, 18, 30, tzinfo=UTC)
    whatsapp_turn = await turn(engine)
    web_turn = await turn(engine, user_hash=WEB_VISITOR)
    before = india_midnight - timedelta(minutes=1)
    after = india_midnight + timedelta(minutes=1)
    await step(engine, whatsapp_turn, "generate", 10, cost="0.5000", started_at=before)
    await step(engine, whatsapp_turn, "generate", 10, cost="0.0200", started_at=after)
    await step(engine, web_turn, "generate", 10, cost="0.0300", started_at=after)
    assert await telemetry.cost_since(india_midnight, None) == Decimal("0.0500")
    assert await telemetry.cost_since(india_midnight, Channel.WEB) == Decimal("0.0300")
    assert await telemetry.cost_since(india_midnight, Channel.WHATSAPP) == Decimal("0.0200")


# --- young learners ------------------------------------------------------------------------------


async def test_young_learner_data_keeps_reports_child_talk_and_activities_apart(
    engine: AsyncEngine, telemetry: TelemetryRepository
) -> None:
    await sql(
        engine,
        "INSERT INTO learners (id, owner_user_hash, relation, nickname, birth_year)"
        " VALUES (:id, :h, 'parent', 'Munni', 2021)",
        id=MUNNI, h=PARENT,
    )  # fmt: skip
    report_turn = await turn(engine)
    talk_turn = await turn(engine)
    for turn_id, source, asked in (
        (report_turn, "parent_report", False),
        (talk_turn, "child_words", True),
    ):
        await sql(
            engine,
            "INSERT INTO curiosity_signals (turn_id, learner_id, source, domains, engagement,"
            " child_asked_question, prompt_version)"
            " VALUES (:t, :l, :s, ARRAY['earth_sky'], 2, :q, '1.0.0')",
            t=turn_id, l=MUNNI, s=source, q=asked,
        )  # fmt: skip
    await sql(
        engine,
        "INSERT INTO learner_activities (id, learner_id, activity_id, activity_version,"
        " offered_turn_id, status, photo_findings) VALUES"
        " (:a, :l, 'stone-tower', 2, :t, 'done', '[{\"phrase\": \"stone\", \"count\": 5}]'),"
        " (:b, :l, 'leaf-families', 2, :t, 'done', '[{\"phrase\": \"leaf\", \"count\": 0}]'),"
        " (:c, :l, 'shadow-time', 2, :t, 'offered', NULL)",
        a=uuid4(), b=uuid4(), c=uuid4(), l=MUNNI, t=report_turn,
    )  # fmt: skip
    await sql(
        engine,
        "INSERT INTO child_sessions (id, user_hash, learner_id, turns_count, end_reason,"
        " ended_at, summary_sent_at) VALUES (:id, :h, :l, 4, 'child_ended', now(), now())",
        id=uuid4(), h=PARENT, l=MUNNI,
    )  # fmt: skip
    data = await telemetry.young_learners()
    learner = LearnerId(MUNNI)
    assert data.owners == {learner: PARENT}
    [report] = data.reports[learner]
    assert report.domains == frozenset({CuriosityDomain.EARTH_SKY})
    assert report.child_asked_question is False
    [words] = data.child_words[learner]
    assert words.child_asked_question is True
    assert data.activities[learner] == ActivityCounts(
        offered=3, done=2, with_photo=2, with_counts=1
    )
    assert data.child_talk[learner].sessions == 1
    assert data.child_talk[learner].turns == 4
    assert data.end_reasons == {ChildSessionEndReason.CHILD_ENDED: 1}
    assert data.summaries_sent == 1


async def test_a_students_own_signals_are_not_young_learner_data(
    engine: AsyncEngine, telemetry: TelemetryRepository
) -> None:
    student = UUID(int=12)
    await sql(
        engine,
        "INSERT INTO learners (id, owner_user_hash, relation, birth_year)"
        " VALUES (:id, :h, 'self', 2012)",
        id=student, h=PARENT,
    )  # fmt: skip
    turn_id = await turn(engine)
    await sql(
        engine,
        "INSERT INTO curiosity_signals (turn_id, learner_id, source, domains, engagement,"
        " child_asked_question, prompt_version)"
        " VALUES (:t, :l, 'parent_report', ARRAY['earth_sky'], 2, false, '1.0.0')",
        t=turn_id, l=student,
    )  # fmt: skip
    data = await telemetry.young_learners()
    assert data.owners == {}
    assert data.reports == {}
