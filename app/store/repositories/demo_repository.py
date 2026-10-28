"""The web demo's reads and counters (s14 §4.3 to §4.7): rate limits, today's web cost, what
became of a message, a visitor's turns for the live trace, and which buttons they were offered.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import and_, delete, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import StoreError
from app.domain.enums import Channel
from app.domain.models.base import UserHash
from app.domain.models.reply import ReplyButton
from app.store.tables import (
    inbox_messages,
    outbox_messages,
    rate_limit_counters,
    turn_steps,
    turns,
    users,
)

_BUTTONS = TypeAdapter(list[ReplyButton])
PRUNE_BATCH = 1000


@dataclass(frozen=True, slots=True)
class RateLimit:
    key: str  # e.g. "demo:session:<user hash>"; never a raw IP
    limit: int
    scope: str  # what the visitor is told: "session", "ip"


@dataclass(frozen=True, slots=True)
class TraceStep:
    step: str
    outcome: str
    duration_ms: int
    detail: str | None
    cost_usd: Decimal | None
    model: str | None = None  # the model behind the step, e.g. muse-spark-open for a reflection


@dataclass(frozen=True, slots=True)
class ReplyPartView:
    part_no: int
    kind: str
    text: str | None
    buttons: list[ReplyButton]
    audio_blob_id: UUID | None
    image_blob_id: UUID | None


@dataclass(frozen=True, slots=True)
class TurnView:
    turn_id: UUID
    status: str
    route: str | None
    steps: list[TraceStep]
    parts: list[ReplyPartView]
    message_ids: list[str]  # the visitor's messages this turn answers; [] for a khoj card


@dataclass(frozen=True, slots=True)
class MessageView:
    """What became of one message: still waiting, or the turn that took it."""

    message_status: str
    turn: TurnView | None


class DemoRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def over_limit(self, limits: Sequence[RateLimit]) -> RateLimit | None:
        """Count this request against every limit, in one transaction. The first limit it
        breaks, or None. An over-limit request is rolled back: nothing counts."""
        try:
            async with self._session_factory() as session, session.begin():
                for limit in limits:
                    count = await _count_hit(session, limit.key)
                    if count > limit.limit:
                        await session.rollback()
                        return limit
                return None
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not count a demo request: {type(exc).__name__}") from exc

    async def prune_rate_limits(self, older_than: timedelta) -> int:
        """Maintenance (s04 §4.13): hourly counter windows nobody can hit any more."""
        stale = (
            select(rate_limit_counters.c.key, rate_limit_counters.c.window_start)
            .where(rate_limit_counters.c.window_start < func.now() - older_than)
            .limit(PRUNE_BATCH)
        )
        try:
            async with self._session_factory() as session, session.begin():
                result = await session.execute(
                    delete(rate_limit_counters)
                    .where(
                        tuple_(rate_limit_counters.c.key, rate_limit_counters.c.window_start).in_(
                            stale
                        )
                    )
                    .returning(rate_limit_counters.c.key)
                )
                return len(result.all())
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not prune rate limits: {type(exc).__name__}") from exc

    async def web_cost_since(self, since: datetime) -> Decimal:
        """Today's spend on web visitors (s14 §4.7)."""
        statement = (
            select(func.coalesce(func.sum(turn_steps.c.cost_usd), 0))
            .select_from(turn_steps)
            .join(turns, turns.c.id == turn_steps.c.turn_id)
            .join(users, users.c.user_hash == turns.c.user_hash)
            .where(and_(users.c.channel == Channel.WEB.value, turn_steps.c.started_at >= since))
        )
        try:
            async with self._session_factory() as session:
                spent = (await session.execute(statement)).scalar_one()
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not read today's cost: {type(exc).__name__}") from exc
        return Decimal(str(spent))

    async def message_view(self, user_hash: UserHash, message_id: str) -> MessageView | None:
        """None when the message doesn't exist or isn't this visitor's (the same answer, so
        ids can't be probed)."""
        try:
            async with self._session_factory() as session:
                message = (
                    await session.execute(
                        select(inbox_messages.c.status, inbox_messages.c.turn_id).where(
                            and_(
                                inbox_messages.c.channel == Channel.WEB.value,
                                inbox_messages.c.external_id == message_id,
                                inbox_messages.c.user_hash == user_hash,
                            )
                        )
                    )
                ).first()
                if message is None:
                    return None
                turn = await _turn_view(session, message.turn_id) if message.turn_id else None
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not read a demo message: {type(exc).__name__}") from exc
        return MessageView(message_status=message.status, turn=turn)

    async def turn_owner(self, turn_id: UUID) -> UserHash | None:
        """Whose turn this is, for routing a progress notification to their stream."""
        try:
            async with self._session_factory() as session:
                owner: str | None = (
                    await session.execute(select(turns.c.user_hash).where(turns.c.id == turn_id))
                ).scalar_one_or_none()
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not read a turn's owner: {type(exc).__name__}") from exc
        return UserHash(owner) if owner is not None else None

    async def visitor_turn(self, user_hash: UserHash, turn_id: UUID) -> TurnView | None:
        """One of this visitor's turns; None for anyone else's (the same answer as none)."""
        try:
            async with self._session_factory() as session:
                owned = (
                    await session.execute(
                        select(turns.c.id).where(
                            and_(turns.c.id == turn_id, turns.c.user_hash == user_hash)
                        )
                    )
                ).first()
                return await _turn_view(session, turn_id) if owned is not None else None
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not read a demo turn: {type(exc).__name__}") from exc

    async def latest_turn(self, user_hash: UserHash, within: timedelta) -> TurnView | None:
        """The visitor's newest turn if it started less than `within` ago: what a stream
        replays when it (re)connects (s14 §4.4)."""
        query = (
            select(turns.c.id)
            .where(and_(turns.c.user_hash == user_hash, turns.c.started_at > func.now() - within))
            .order_by(turns.c.started_at.desc())
            .limit(1)
        )
        try:
            async with self._session_factory() as session:
                turn_id: UUID | None = (await session.execute(query)).scalar_one_or_none()
                return await _turn_view(session, turn_id) if turn_id is not None else None
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not read the latest demo turn: {type(exc).__name__}") from exc

    async def offered_buttons(self, user_hash: UserHash) -> set[str]:
        """Button ids in the visitor's latest reply: a button press must be one of them."""
        latest_turn = (
            select(outbox_messages.c.turn_id)
            .where(outbox_messages.c.user_hash == user_hash)
            .order_by(outbox_messages.c.created_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        statement = select(outbox_messages.c.buttons).where(
            outbox_messages.c.turn_id == latest_turn
        )
        try:
            async with self._session_factory() as session:
                rows = (await session.execute(statement)).scalars().all()
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not read offered buttons: {type(exc).__name__}") from exc
        offered: set[str] = set()
        for buttons in rows:
            offered.update(button.id for button in _BUTTONS.validate_python(buttons))
        return offered


async def _count_hit(session: AsyncSession, key: str) -> int:
    window = func.date_trunc("hour", func.now())
    statement = (
        insert(rate_limit_counters)
        .values(key=key, window_start=window, count=1)
        .on_conflict_do_update(
            index_elements=["key", "window_start"],
            set_={"count": rate_limit_counters.c.count + 1},
        )
        .returning(rate_limit_counters.c.count)
    )
    count: int = (await session.execute(statement)).scalar_one()
    return count


async def _turn_view(session: AsyncSession, turn_id: UUID) -> TurnView | None:
    turn = (
        await session.execute(select(turns.c.status, turns.c.route).where(turns.c.id == turn_id))
    ).first()
    if turn is None:
        return None
    steps = (
        await session.execute(
            select(
                turn_steps.c.step,
                turn_steps.c.outcome,
                turn_steps.c.duration_ms,
                turn_steps.c.detail,
                turn_steps.c.cost_usd,
                turn_steps.c.model,
            )
            .where(turn_steps.c.turn_id == turn_id)
            .order_by(turn_steps.c.id)
        )
    ).all()
    parts = (
        await session.execute(
            select(outbox_messages)
            .where(outbox_messages.c.turn_id == turn_id)
            .order_by(outbox_messages.c.part_no)
        )
    ).all()
    message_ids = (
        (
            await session.execute(
                select(inbox_messages.c.external_id)
                .where(inbox_messages.c.turn_id == turn_id)
                .order_by(inbox_messages.c.id)
            )
        )
        .scalars()
        .all()
    )
    return TurnView(
        turn_id=turn_id,
        status=turn.status,
        route=turn.route,
        steps=[
            TraceStep(row.step, row.outcome, row.duration_ms, row.detail, row.cost_usd, row.model)
            for row in steps
        ],
        parts=[
            ReplyPartView(
                part_no=row.part_no,
                kind=row.kind,
                text=row.text,
                buttons=_BUTTONS.validate_python(row.buttons),
                audio_blob_id=row.audio_blob_id,
                image_blob_id=row.image_blob_id,
            )
            for row in parts
        ],
        message_ids=list(message_ids),
    )
