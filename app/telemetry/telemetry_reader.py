"""TelemetryReader: what the /status and dashboard builders read (TelemetryRepository in
production, a fake in unit tests)."""

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from app.domain.enums import Channel
from app.store.repositories.telemetry_repository import (
    FailureCountRow,
    JourneyCountsRow,
    StepLatencyRow,
    StudentData,
    TurnSummaryRow,
    YoungLearnerData,
)


class TelemetryReader(Protocol):
    async def step_latency_24h(self) -> list[StepLatencyRow]: ...

    async def turn_summary_24h(self) -> TurnSummaryRow: ...

    async def journey_counts_24h(self) -> JourneyCountsRow: ...

    async def failures_24h(self) -> list[FailureCountRow]: ...

    async def cost_since(self, since: datetime, channel: Channel | None) -> Decimal: ...

    async def young_learners(self) -> YoungLearnerData: ...

    async def students(self, district: str | None = None) -> StudentData: ...
