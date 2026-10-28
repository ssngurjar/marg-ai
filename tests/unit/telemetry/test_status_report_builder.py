"""StatusReportBuilder: public numbers for everyone, cost and crisis for admin (s13 §4.7, B8)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core.errors import StoreError
from app.domain.enums import Channel
from app.store.repositories.telemetry_repository import (
    FailureCountRow,
    JourneyCountsRow,
    StepLatencyRow,
    TurnSummaryRow,
)
from app.telemetry.status_report_builder import StatusReportBuilder, StatusSettings
from tests.fakes.clock import FixedClock
from tests.fakes.telemetry_reader import FakeTelemetryReader

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 28, 20, 0, tzinfo=UTC)  # 01:30 IST on Oct 29
INDIA_MIDNIGHT = datetime(2026, 10, 28, 18, 30, tzinfo=UTC)


def reader() -> FakeTelemetryReader:
    return FakeTelemetryReader(
        steps=[StepLatencyRow("generate", 10, 3210.4, 5999.6, 0.9, 0.1)],
        summary=TurnSummaryRow(
            turns=12,
            served_ok_rate=0.75,
            p50_user_ms=4321.6,
            p95_user_ms=None,
            crisis_turns=1,
            journey_turns=9,
            nudges_sent=2,
        ),
        journey=JourneyCountsRow(photos_received=3, photos_refused=1, cards_sent=2),
        failures=[FailureCountRow("safety_in", "provider_timeout", 2)],
        costs={None: Decimal("0.4200"), Channel.WEB: Decimal("0.1000")},
    )


def builder(source: FakeTelemetryReader) -> StatusReportBuilder:
    return StatusReportBuilder(source, FixedClock(NOW), StatusSettings(Decimal(5)))


async def test_the_public_report_has_latency_success_and_journey_counts_only() -> None:
    report = await builder(reader()).build(include_admin=False)
    assert (report.turns, report.served_ok_rate) == (12, 0.75)
    assert (report.p50_user_ms, report.p95_user_ms) == (4322, None)
    assert [(s.step, s.p50_ms, s.p95_ms) for s in report.steps] == [("generate", 3210, 6000)]
    assert report.journey.photos_refused == 1
    assert report.journey.cards_sent == 2
    assert report.admin is None


async def test_the_admin_report_adds_todays_cost_crisis_and_failures() -> None:
    source = reader()
    report = await builder(source).build(include_admin=True)
    assert report.admin is not None
    assert report.admin.cost_today_usd == Decimal("0.4200")
    assert report.admin.web_cost_today_usd == Decimal("0.1000")
    assert report.admin.web_daily_cap_usd == Decimal(5)
    assert report.admin.crisis_turns == 1
    assert [(f.step, f.turns) for f in report.admin.failures] == [("safety_in", 2)]


async def test_today_starts_at_india_midnight() -> None:
    source = reader()
    await builder(source).build(include_admin=True)
    assert source.cost_reads == [(INDIA_MIDNIGHT, None), (INDIA_MIDNIGHT, Channel.WEB)]


async def test_the_public_report_never_reads_cost() -> None:
    source = reader()
    await builder(source).build(include_admin=False)
    assert source.cost_reads == []


async def test_a_database_failure_is_a_store_error() -> None:
    with pytest.raises(StoreError, match="could not read telemetry"):
        await builder(FakeTelemetryReader(broken=True)).build(include_admin=False)
