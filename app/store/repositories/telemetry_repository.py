"""TelemetryRepository: the aggregate reads behind /status and the dashboard (s13 §4.6).

Read-only. Latency and success come from the `turn_metrics` view and `turn_steps`; the young
learners' curiosity from `curiosity_signals`, `learner_activities` and `child_sessions`. Learner
ids and user hashes never leave this module and the telemetry builders: pages get counts only.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Row, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import StoreError
from app.domain.enums import Channel, ChildSessionEndReason, CuriosityDomain
from app.domain.models.base import UserHash
from app.domain.models.learner import LearnerId
from app.domain.rules.curiosity_trajectory import CuriosityPoint


@dataclass(frozen=True, slots=True)
class StepLatencyRow:
    step: str
    runs: int
    p50_ms: float
    p95_ms: float
    ok_rate: float
    degraded_rate: float


@dataclass(frozen=True, slots=True)
class TurnSummaryRow:
    turns: int
    served_ok_rate: float | None  # None with no turns
    p50_user_ms: float | None  # None when no turn has a user latency (nudges have none)
    p95_user_ms: float | None
    crisis_turns: int
    journey_turns: int
    nudges_sent: int


@dataclass(frozen=True, slots=True)
class JourneyCountsRow:
    photos_received: int  # photos that reached the person check
    photos_refused: int  # PHOTO_HAS_PERSON replies
    cards_sent: int


@dataclass(frozen=True, slots=True)
class FailureCountRow:
    step: str
    failure_kind: str
    turns: int


@dataclass(frozen=True, slots=True)
class ActivityCounts:
    offered: int
    done: int
    with_photo: int  # done with a photo that was checked (photo_findings set)
    with_counts: int  # ... and something counted in it


@dataclass(frozen=True, slots=True)
class ChildTalkCounts:
    sessions: int
    turns: int


@dataclass
class YoungLearnerData:
    """Everything the young-learner section is computed from, keyed by child."""

    owners: dict[LearnerId, UserHash] = field(default_factory=dict)
    reports: dict[LearnerId, list[CuriosityPoint]] = field(default_factory=dict)  # parent reports
    child_words: dict[LearnerId, list[CuriosityPoint]] = field(default_factory=dict)  # child talk
    activities: dict[LearnerId, ActivityCounts] = field(default_factory=dict)
    child_talk: dict[LearnerId, ChildTalkCounts] = field(default_factory=dict)
    end_reasons: dict[ChildSessionEndReason, int] = field(default_factory=dict)
    summaries_sent: int = 0
    cards_sent: int = 0


class TelemetryRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def step_latency_24h(self) -> list[StepLatencyRow]:
        rows = await self._rows(
            """
            SELECT step,
                   count(*) AS runs,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms) AS p50_ms,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms,
                   avg((outcome IN ('ok', 'degraded'))::int) AS ok_rate,
                   avg((outcome = 'degraded')::int) AS degraded_rate
            FROM turn_steps
            WHERE started_at >= now() - interval '24 hours' AND outcome <> 'skipped'
            GROUP BY step
            ORDER BY step
            """
        )
        return [
            StepLatencyRow(
                step=row.step,
                runs=int(row.runs),
                p50_ms=float(row.p50_ms),
                p95_ms=float(row.p95_ms),
                ok_rate=float(row.ok_rate),
                degraded_rate=float(row.degraded_rate),
            )
            for row in rows
        ]

    async def turn_summary_24h(self) -> TurnSummaryRow:
        [row] = await self._rows(
            """
            SELECT count(*) AS turns,
                   avg(served_ok::int) AS served_ok_rate,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY user_latency_ms) AS p50_user_ms,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY user_latency_ms) AS p95_user_ms,
                   count(*) FILTER (WHERE fixed_reply_kind = 'crisis') AS crisis_turns,
                   count(*) FILTER (WHERE route = 'journey') AS journey_turns,
                   count(*) FILTER (WHERE route = 'nudge') AS nudges_sent
            FROM turn_metrics
            WHERE started_at >= now() - interval '24 hours'
            """
        )
        return TurnSummaryRow(
            turns=int(row.turns),
            served_ok_rate=_optional_float(row.served_ok_rate),
            p50_user_ms=_optional_float(row.p50_user_ms),
            p95_user_ms=_optional_float(row.p95_user_ms),
            crisis_turns=int(row.crisis_turns),
            journey_turns=int(row.journey_turns),
            nudges_sent=int(row.nudges_sent),
        )

    async def journey_counts_24h(self) -> JourneyCountsRow:
        [row] = await self._rows(
            """
            SELECT
              (SELECT count(*) FROM turn_steps
               WHERE step = 'analyze_image' AND detail LIKE 'person_check=%'
                 AND started_at >= now() - interval '24 hours') AS photos_received,
              (SELECT count(*) FROM turns
               WHERE fixed_reply_kind = 'photo_has_person'
                 AND started_at >= now() - interval '24 hours') AS photos_refused,
              (SELECT count(*) FROM turn_steps
               WHERE step = 'make_card' AND outcome = 'ok' AND detail = 'sent'
                 AND started_at >= now() - interval '24 hours') AS cards_sent
            """
        )
        return JourneyCountsRow(
            photos_received=int(row.photos_received),
            photos_refused=int(row.photos_refused),
            cards_sent=int(row.cards_sent),
        )

    async def failures_24h(self) -> list[FailureCountRow]:
        rows = await self._rows(
            """
            SELECT step, failure_kind, count(*) AS turns
            FROM turn_steps
            WHERE outcome = 'failed' AND started_at >= now() - interval '24 hours'
            GROUP BY step, failure_kind
            ORDER BY step, failure_kind
            """
        )
        return [
            FailureCountRow(step=row.step, failure_kind=row.failure_kind, turns=int(row.turns))
            for row in rows
        ]

    async def cost_since(self, since: datetime, channel: Channel | None) -> Decimal:
        """What the providers cost since `since` (the start of the India day for "today"),
        for one channel's users or all."""
        [row] = await self._rows(
            """
            SELECT COALESCE(sum(s.cost_usd), 0) AS cost
            FROM turn_steps s
            JOIN turns t ON t.id = s.turn_id
            JOIN users u ON u.user_hash = t.user_hash
            WHERE s.started_at >= :since
              AND (CAST(:channel AS text) IS NULL OR u.channel = :channel)
            """,
            since=since,
            channel=channel.value if channel else None,
        )
        return Decimal(row.cost)

    async def young_learners(self) -> YoungLearnerData:
        """Parents' children with their reports' curiosity, activities, child talk and cards."""
        try:
            async with self._session_factory() as session:
                return await _young_learners(session)
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not read young learners: {type(exc).__name__}") from exc

    async def _rows(self, sql: str, **params: object) -> list[Row[tuple[object, ...]]]:
        try:
            async with self._session_factory() as session:
                result = await session.execute(text(sql), params)
                return list(result.all())
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not read telemetry: {type(exc).__name__}") from exc


async def _young_learners(session: AsyncSession) -> YoungLearnerData:
    data = YoungLearnerData()
    learners = await session.execute(
        text("SELECT id, owner_user_hash FROM learners WHERE relation = 'parent'")
    )
    for row in learners.all():
        data.owners[LearnerId(row.id)] = UserHash(row.owner_user_hash)
    signals = await session.execute(
        text(
            """
            SELECT c.learner_id, c.source, t.started_at, c.domains, c.engagement,
                   c.child_asked_question
            FROM curiosity_signals c
            JOIN turns t ON t.id = c.turn_id
            JOIN learners l ON l.id = c.learner_id
            WHERE l.relation = 'parent'
            ORDER BY c.learner_id, t.started_at
            """
        )
    )
    reports: defaultdict[LearnerId, list[CuriosityPoint]] = defaultdict(list)
    child_words: defaultdict[LearnerId, list[CuriosityPoint]] = defaultdict(list)
    for row in signals.all():
        learner_id = LearnerId(row.learner_id)
        point = CuriosityPoint(
            at=row.started_at,
            domains=frozenset(CuriosityDomain(domain) for domain in row.domains),
            engagement=row.engagement,
            child_asked_question=row.child_asked_question,
        )
        target = child_words if row.source == "child_words" else reports
        target[learner_id].append(point)
    data.reports = dict(reports)
    data.child_words = dict(child_words)
    activities = await session.execute(
        text(
            """
            SELECT learner_id,
                   count(*) AS offered,
                   count(*) FILTER (WHERE status = 'done') AS done,
                   count(*) FILTER (WHERE photo_findings IS NOT NULL) AS with_photo,
                   count(*) FILTER (
                       WHERE EXISTS (
                           SELECT 1 FROM jsonb_array_elements(photo_findings) AS found
                           WHERE (found ->> 'count')::int > 0
                       )
                   ) AS with_counts
            FROM learner_activities
            GROUP BY learner_id
            """
        )
    )
    for row in activities.all():
        data.activities[LearnerId(row.learner_id)] = ActivityCounts(
            offered=int(row.offered),
            done=int(row.done),
            with_photo=int(row.with_photo),
            with_counts=int(row.with_counts),
        )
    sessions = await session.execute(
        text(
            """
            SELECT learner_id, count(*) AS sessions, COALESCE(sum(turns_count), 0) AS turns
            FROM child_sessions GROUP BY learner_id
            """
        )
    )
    for row in sessions.all():
        data.child_talk[LearnerId(row.learner_id)] = ChildTalkCounts(
            sessions=int(row.sessions), turns=int(row.turns)
        )
    endings = await session.execute(
        text(
            """
            SELECT end_reason, count(*) AS sessions FROM child_sessions
            WHERE end_reason IS NOT NULL GROUP BY end_reason
            """
        )
    )
    for row in endings.all():
        data.end_reasons[ChildSessionEndReason(row.end_reason)] = int(row.sessions)
    totals = await session.execute(
        text(
            """
            SELECT
              (SELECT count(*) FROM child_sessions WHERE summary_sent_at IS NOT NULL) AS summaries,
              (SELECT count(*) FROM turn_steps
               WHERE step = 'make_card' AND outcome = 'ok' AND detail = 'sent') AS cards
            """
        )
    )
    total = totals.one()
    data.summaries_sent = int(total.summaries)
    data.cards_sent = int(total.cards)
    return data


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float | Decimal):
        return float(value)
    raise StoreError(f"expected a number from telemetry, got {type(value).__name__}")
