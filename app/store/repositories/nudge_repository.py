"""Daily khoj messages: who opted in, and the NUDGE turns that send them (s10b §4.11).

A nudge is a turn with no inbound message and one TEMPLATE part, inserted through the same
sealed outbox path as every reply (OutboxRepository.enqueue takes only a ReplyDelivery).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time
from uuid import uuid4

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import StoreError
from app.domain.enums import (
    Channel,
    ConversationState,
    FixedReplyKind,
    Language,
    Role,
    Route,
    TurnStatus,
)
from app.domain.models.base import TurnId, UserHash
from app.domain.models.writes import NudgePreference
from app.domain.rules.nudge_schedule import NudgeSchedule
from app.pipeline.reply_parts_builder import ReplyDelivery
from app.store.repositories.outbox_repository import OutboxRepository
from app.store.tables import nudge_subscriptions, turns, users

FALLBACK_LANGUAGE = Language.HINGLISH


@dataclass(frozen=True, slots=True)
class NudgeBatch:
    """What one maintenance pass may send."""

    deliveries: Mapping[Language, ReplyDelivery]  # the sealed template part, per language
    reply_texts: Mapping[Language, str]  # the template's text, recorded on the turn
    worker_id: str
    batch_size: int  # parents claimed per pass
    daily_limit: int  # NUDGE_DAILY_LIMIT, across all parents (Meta's unverified cap is 250)


@dataclass(frozen=True, slots=True)
class NudgeResult:
    sent: list[TurnId]
    skipped: int


class NudgeRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    async def set_preference(
        session: AsyncSession, owner: UserHash, write: NudgePreference
    ) -> None:
        """Inside finalize: turn the daily message on at a time, or off."""
        now: datetime = (await session.execute(select(func.now()))).scalar_one()
        if write.enabled and write.local_time is None:
            raise StoreError("turning nudges on needs a time")
        next_due = (
            NudgeSchedule.next_due(write.local_time, now)
            if write.enabled and write.local_time
            else None
        )
        values: dict[str, object] = {
            "enabled": write.enabled,
            "local_time": write.local_time if write.enabled else None,
            "next_due_at": next_due,
        }
        values["opted_in_at" if write.enabled else "opted_out_at"] = now
        statement = insert(nudge_subscriptions).values(user_hash=owner, **values)
        await session.execute(
            statement.on_conflict_do_update(index_elements=["user_hash"], set_=values)
        )

    async def send_due(self, batch: NudgeBatch, now: datetime) -> NudgeResult:
        """Claim parents due by `now` (SKIP LOCKED) and, in one transaction, either queue their
        nudge turn or reschedule them: quiet hours, a khoj turn already today, or the day's
        cap. `now` comes from the worker's clock, so the rules can be tested."""
        try:
            async with self._session_factory() as session, session.begin():
                day_start = NudgeSchedule.start_of_india_day(now)
                sent_today = await _nudges_since(session, day_start)
                due = await _claim_due(session, batch.batch_size, now)
                sent: list[TurnId] = []
                skipped = 0
                for parent in due:
                    over_cap = sent_today + len(sent) >= batch.daily_limit
                    reschedule: dict[str, object] = {
                        "next_due_at": NudgeSchedule.next_due(parent.local_time, now)
                    }
                    if (
                        NudgeSchedule.in_quiet_hours(now)
                        or over_cap
                        or await _had_khoj_today(session, parent.user_hash, day_start)
                    ):
                        skipped += 1
                    else:
                        sent.append(await _queue(session, parent, batch))
                        reschedule["last_sent_at"] = now
                    await session.execute(
                        update(nudge_subscriptions)
                        .where(nudge_subscriptions.c.user_hash == parent.user_hash)
                        .values(**reschedule)
                    )
                return NudgeResult(sent=sent, skipped=skipped)
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not send nudges: {type(exc).__name__}") from exc


@dataclass(frozen=True, slots=True)
class _DueParent:
    user_hash: UserHash
    local_time: time
    language: Language


async def _claim_due(session: AsyncSession, limit: int, now: datetime) -> list[_DueParent]:
    rows = (
        await session.execute(
            select(
                nudge_subscriptions.c.user_hash, nudge_subscriptions.c.local_time, users.c.language
            )
            .join(users, users.c.user_hash == nudge_subscriptions.c.user_hash)
            .where(
                and_(
                    nudge_subscriptions.c.enabled,
                    nudge_subscriptions.c.next_due_at <= now,
                    users.c.state == ConversationState.ACTIVE.value,
                    users.c.role == Role.PARENT.value,
                    users.c.channel == Channel.WHATSAPP.value,
                )
            )
            .order_by(nudge_subscriptions.c.next_due_at)
            .limit(limit)
            .with_for_update(of=nudge_subscriptions, skip_locked=True)
        )
    ).all()
    return [
        _DueParent(
            user_hash=UserHash(row.user_hash),
            local_time=row.local_time,
            language=Language(row.language or FALLBACK_LANGUAGE),
        )
        for row in rows
    ]


async def _nudges_since(session: AsyncSession, day_start: datetime) -> int:
    count: int = (
        await session.execute(
            select(func.count())
            .select_from(turns)
            .where(and_(turns.c.route == Route.NUDGE.value, turns.c.started_at >= day_start))
        )
    ).scalar_one()
    return count


async def _had_khoj_today(session: AsyncSession, user_hash: UserHash, day_start: datetime) -> bool:
    found = await session.execute(
        select(turns.c.id)
        .where(
            and_(
                turns.c.user_hash == user_hash,
                turns.c.route == Route.JOURNEY.value,
                turns.c.started_at >= day_start,
            )
        )
        .limit(1)
    )
    return found.first() is not None


async def _queue(session: AsyncSession, parent: _DueParent, batch: NudgeBatch) -> TurnId:
    turn_id = TurnId(uuid4())
    user_hash, language = parent.user_hash, parent.language
    await session.execute(
        turns.insert().values(
            id=turn_id,
            user_hash=user_hash,
            status=TurnStatus.COMPLETED.value,
            route=Route.NUDGE.value,
            reply_text=batch.reply_texts[language],
            reply_register=language.value,
            fixed_reply_kind=FixedReplyKind.NUDGE.value,
            worker_id=batch.worker_id,
            completed_at=func.now(),
        )
    )
    await OutboxRepository.enqueue(
        session, turn_id, user_hash, Channel.WHATSAPP, batch.deliveries[language]
    )
    return turn_id
