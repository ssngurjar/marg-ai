"""StatusReportBuilder: what /status shows (s13 §4.7; public fields per decision B8).

Everyone sees latency, success and journey counts for the last 24 hours. The admin scope also
sees today's cost (all channels, and the web demo's against its cap), crisis turns and failures
by step. Numbers only: no text, hashes or names.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.core.clock import Clock
from app.domain.enums import Channel
from app.domain.rules.nudge_schedule import NudgeSchedule
from app.telemetry.telemetry_reader import TelemetryReader


class StepLatency(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    step: str
    runs: int
    p50_ms: int
    p95_ms: int
    ok_rate: float
    degraded_rate: float


class JourneyCounts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    journey_turns: int
    nudges_sent: int
    photos_received: int
    photos_refused: int
    cards_sent: int


class FailureCount(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    step: str
    failure_kind: str
    turns: int


class AdminStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cost_today_usd: Decimal
    web_cost_today_usd: Decimal
    web_daily_cap_usd: Decimal
    crisis_turns: int
    failures: list[FailureCount]


class StatusReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime
    turns: int
    served_ok_rate: float | None
    p50_user_ms: int | None
    p95_user_ms: int | None
    steps: list[StepLatency]
    journey: JourneyCounts
    admin: AdminStatus | None  # None outside the admin scope


@dataclass(frozen=True, slots=True)
class StatusSettings:
    web_daily_cap_usd: Decimal  # DAILY_COST_CAP_USD


class StatusReportBuilder:
    def __init__(self, reader: TelemetryReader, clock: Clock, settings: StatusSettings) -> None:
        self._reader = reader
        self._clock = clock
        self._settings = settings

    async def build(self, *, include_admin: bool) -> StatusReport:
        """Raises StoreError when the database can't be read."""
        now = self._clock.now()
        summary = await self._reader.turn_summary_24h()
        counts = await self._reader.journey_counts_24h()
        steps = [
            StepLatency(
                step=row.step,
                runs=row.runs,
                p50_ms=round(row.p50_ms),
                p95_ms=round(row.p95_ms),
                ok_rate=row.ok_rate,
                degraded_rate=row.degraded_rate,
            )
            for row in await self._reader.step_latency_24h()
        ]
        return StatusReport(
            generated_at=now,
            turns=summary.turns,
            served_ok_rate=summary.served_ok_rate,
            p50_user_ms=_rounded(summary.p50_user_ms),
            p95_user_ms=_rounded(summary.p95_user_ms),
            steps=steps,
            journey=JourneyCounts(
                journey_turns=summary.journey_turns,
                nudges_sent=summary.nudges_sent,
                photos_received=counts.photos_received,
                photos_refused=counts.photos_refused,
                cards_sent=counts.cards_sent,
            ),
            admin=await self._admin(now, summary.crisis_turns) if include_admin else None,
        )

    async def _admin(self, now: datetime, crisis_turns: int) -> AdminStatus:
        today = NudgeSchedule.start_of_india_day(now)
        failures = [
            FailureCount(step=row.step, failure_kind=row.failure_kind, turns=row.turns)
            for row in await self._reader.failures_24h()
        ]
        return AdminStatus(
            cost_today_usd=await self._reader.cost_since(today, None),
            web_cost_today_usd=await self._reader.cost_since(today, Channel.WEB),
            web_daily_cap_usd=self._settings.web_daily_cap_usd,
            crisis_turns=crisis_turns,
            failures=failures,
        )


def _rounded(value: float | None) -> int | None:
    return round(value) if value is not None else None
