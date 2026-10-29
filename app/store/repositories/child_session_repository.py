"""Child sessions: a child talking to Marg.ai directly (s10b §4.16, data-model `child_sessions`).

Writes run inside the finalize transaction, only for the user's own children. A session keeps
counts and topics (curiosity domains), never what the child said.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, and_, func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import StoreError
from app.domain.enums import (
    Channel,
    ChildSessionEndReason,
    CuriosityDomain,
    FixedReplyKind,
    Language,
    Route,
    TurnStatus,
)
from app.domain.models.base import TurnId, UserHash
from app.domain.models.child_session import ChildSession
from app.domain.models.learner import LearnerId
from app.domain.models.writes import (
    ChildSessionEnd,
    ChildSessionLanguage,
    ChildSessionStart,
    ChildTalkTurn,
)
from app.pipeline.reply_parts_builder import ReplyDelivery
from app.store.repositories.outbox_repository import OutboxRepository
from app.store.tables import child_sessions, learners, turns, users
from app.store.turn_progress_notifier import TurnProgressNotifier


@dataclass(frozen=True, slots=True)
class ExpiredSession:
    """A session closed without a goodbye: what its parent's summary needs (topics, never the
    child's words)."""

    session_id: UUID
    user_hash: UserHash
    channel: Channel
    language: Language | None
    nickname: str | None
    topics: list[CuriosityDomain]


@dataclass(frozen=True, slots=True)
class QueuedSummary:
    expired: ExpiredSession
    delivery: ReplyDelivery  # sealed by the safety gate
    reply_text: str
    register: Language
    worker_id: str


class ChildSessionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    async def open_for(session: AsyncSession, user_hash: UserHash) -> ChildSession | None:
        row = (
            await session.execute(
                select(child_sessions).where(
                    and_(
                        child_sessions.c.user_hash == user_hash, child_sessions.c.ended_at.is_(None)
                    )
                )
            )
        ).first()
        if row is None:
            return None
        return ChildSession(
            id=row.id,
            learner_id=LearnerId(row.learner_id),
            started_at=row.started_at,
            turns_count=row.turns_count,
            topics=[CuriosityDomain(topic) for topic in row.topics],
            language=Language(row.language) if row.language is not None else None,
        )

    @staticmethod
    async def last_ended_at(session: AsyncSession, user_hash: UserHash) -> datetime | None:
        """When the last session in which the child asked something ended (for the cooldown).
        A session with no answered question doesn't count (owner, 2026-10-29)."""
        ended: datetime | None = (
            await session.execute(
                select(func.max(child_sessions.c.ended_at)).where(
                    and_(
                        child_sessions.c.user_hash == user_hash,
                        child_sessions.c.turns_count > 0,
                    )
                )
            )
        ).scalar_one()
        return ended

    @staticmethod
    async def start(session: AsyncSession, owner: UserHash, write: ChildSessionStart) -> None:
        owned = await session.execute(
            select(learners.c.id).where(
                and_(learners.c.id == write.learner_id, learners.c.owner_user_hash == owner)
            )
        )
        if owned.first() is None:
            raise StoreError("a child session can only start for the user's own learner")
        await session.execute(
            child_sessions.insert().values(
                id=write.session_id, learner_id=write.learner_id, user_hash=owner
            )
        )

    @staticmethod
    async def set_language(
        session: AsyncSession, owner: UserHash, write: ChildSessionLanguage
    ) -> None:
        await session.execute(
            update(child_sessions)
            .where(_open_session(owner, write.session_id))
            .values(language=write.language.value)
        )

    @staticmethod
    async def count_turn(session: AsyncSession, owner: UserHash, write: ChildTalkTurn) -> None:
        values: dict[str, object] = {"turns_count": child_sessions.c.turns_count + 1}
        if write.topic is not None:
            topic = write.topic.value
            values["topics"] = func.array_append(
                func.array_remove(child_sessions.c.topics, topic), topic
            )
        await session.execute(
            update(child_sessions).where(_open_session(owner, write.session_id)).values(**values)
        )

    @staticmethod
    async def end(session: AsyncSession, owner: UserHash, write: ChildSessionEnd) -> None:
        """Ends it, and records that the summary went with this turn's reply (none after a
        crisis: the orchestrator decides what the parent sees)."""
        summary_sent = write.reason is not ChildSessionEndReason.CRISIS
        await session.execute(
            update(child_sessions)
            .where(_open_session(owner, write.session_id))
            .values(
                ended_at=func.now(),
                end_reason=write.reason.value,
                summary_sent_at=func.now() if summary_sent else None,
            )
        )

    async def close_abandoned(self, older_than: timedelta) -> int:
        """Maintenance: sessions the child left without a goodbye, past the time limit. Closed as
        EXPIRED; ChildSessionSummarySender then sends the parent their summary."""
        statement = (
            update(child_sessions)
            .where(
                and_(
                    child_sessions.c.ended_at.is_(None),
                    child_sessions.c.started_at < func.now() - older_than,
                )
            )
            .values(ended_at=func.now(), end_reason=ChildSessionEndReason.EXPIRED.value)
            .returning(child_sessions.c.id)
        )
        try:
            async with self._session_factory() as session, session.begin():
                return len((await session.execute(statement)).all())
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not close child sessions: {type(exc).__name__}") from exc

    async def due_summaries(self, limit: int, window: timedelta) -> list[ExpiredSession]:
        """Expired sessions whose parent hasn't had the summary, still inside `window` (WhatsApp's
        24 hours: a free-form reply can't go later; the web has none). Older ones are never sent,
        nor one in which the child asked nothing: there's nothing true to tell (owner,
        2026-10-29)."""
        window_open = or_(
            users.c.channel == Channel.WEB.value,
            users.c.last_inbound_at > func.now() - window,
        )
        query = (
            select(
                child_sessions.c.id,
                child_sessions.c.user_hash,
                child_sessions.c.topics,
                learners.c.nickname,
                users.c.channel,
                users.c.language,
            )
            .join(learners, learners.c.id == child_sessions.c.learner_id)
            .join(users, users.c.user_hash == child_sessions.c.user_hash)
            .where(
                and_(
                    child_sessions.c.end_reason == ChildSessionEndReason.EXPIRED.value,
                    child_sessions.c.summary_sent_at.is_(None),
                    child_sessions.c.turns_count > 0,
                    child_sessions.c.ended_at > func.now() - window,
                    window_open,
                )
            )
            .order_by(child_sessions.c.ended_at)
            .limit(limit)
        )
        try:
            async with self._session_factory() as session:
                rows = (await session.execute(query)).all()
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not read due summaries: {type(exc).__name__}") from exc
        return [
            ExpiredSession(
                session_id=row.id,
                user_hash=UserHash(row.user_hash),
                channel=Channel(row.channel),
                language=Language(row.language) if row.language else None,
                nickname=row.nickname,
                topics=[CuriosityDomain(topic) for topic in row.topics],
            )
            for row in rows
        ]

    async def queue_summary(self, summary: QueuedSummary) -> TurnId | None:
        """Mark the summary sent and queue its turn, in one transaction. None when another
        worker got there first, or the parent was deleted meanwhile."""
        expired = summary.expired
        try:
            async with self._session_factory() as session, session.begin():
                claimed = (
                    await session.execute(
                        update(child_sessions)
                        .where(
                            and_(
                                child_sessions.c.id == expired.session_id,
                                child_sessions.c.summary_sent_at.is_(None),
                            )
                        )
                        .values(summary_sent_at=func.now())
                        .returning(child_sessions.c.id)
                    )
                ).first()
                if claimed is None:
                    return None
                turn_id = TurnId(uuid4())
                await session.execute(
                    turns.insert().values(
                        id=turn_id,
                        user_hash=expired.user_hash,
                        status=TurnStatus.COMPLETED.value,
                        route=Route.CHILD_TALK.value,
                        reply_text=summary.reply_text,
                        reply_register=summary.register.value,
                        fixed_reply_kind=FixedReplyKind.CHILD_SESSION_END.value,
                        worker_id=summary.worker_id,
                        completed_at=func.now(),
                    )
                )
                await OutboxRepository.enqueue(
                    session, turn_id, expired.user_hash, expired.channel, summary.delivery
                )
                await TurnProgressNotifier.notify(session, turn_id)
                return turn_id
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not queue a session summary: {type(exc).__name__}") from exc


def _open_session(owner: UserHash, session_id: UUID) -> ColumnElement[bool]:
    return and_(
        child_sessions.c.id == session_id,
        child_sessions.c.user_hash == owner,
        child_sessions.c.ended_at.is_(None),
    )
