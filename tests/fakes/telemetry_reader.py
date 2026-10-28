"""A fake TelemetryReader: scripted rows, or a StoreError for every read."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.core.errors import StoreError
from app.domain.enums import Channel
from app.store.repositories.telemetry_repository import (
    FailureCountRow,
    JourneyCountsRow,
    StepLatencyRow,
    StudentData,
    TurnSummaryRow,
    YoungLearnerData,
)

EMPTY_SUMMARY = TurnSummaryRow(
    turns=0,
    served_ok_rate=None,
    p50_user_ms=None,
    p95_user_ms=None,
    crisis_turns=0,
    journey_turns=0,
    nudges_sent=0,
)


@dataclass
class FakeTelemetryReader:
    """Satisfies `TelemetryReader`. Records the `since` and channel of every cost read."""

    steps: list[StepLatencyRow] = field(default_factory=list)
    summary: TurnSummaryRow = EMPTY_SUMMARY
    journey: JourneyCountsRow = field(default_factory=lambda: JourneyCountsRow(0, 0, 0))
    failures: list[FailureCountRow] = field(default_factory=list)
    costs: dict[Channel | None, Decimal] = field(default_factory=dict)
    young: YoungLearnerData = field(default_factory=YoungLearnerData)
    student: StudentData = field(default_factory=StudentData)
    broken: bool = False
    cost_reads: list[tuple[datetime, Channel | None]] = field(default_factory=list)

    async def step_latency_24h(self) -> list[StepLatencyRow]:
        self._check()
        return self.steps

    async def turn_summary_24h(self) -> TurnSummaryRow:
        self._check()
        return self.summary

    async def journey_counts_24h(self) -> JourneyCountsRow:
        self._check()
        return self.journey

    async def failures_24h(self) -> list[FailureCountRow]:
        self._check()
        return self.failures

    async def cost_since(self, since: datetime, channel: Channel | None) -> Decimal:
        self._check()
        self.cost_reads.append((since, channel))
        return self.costs.get(channel, Decimal(0))

    async def young_learners(self) -> YoungLearnerData:
        self._check()
        return self.young

    async def students(self) -> StudentData:
        self._check()
        return self.student

    def _check(self) -> None:
        if self.broken:
            raise StoreError("could not read telemetry: OperationalError")
