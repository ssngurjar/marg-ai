"""Child sessions: a child talking to Marg.ai directly (s10b §4.16, data-model `child_sessions`).

Writes run inside the finalize transaction, only for the user's own children. A session keeps
counts and topics (curiosity domains), never what the child said.
"""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import StoreError
from app.domain.enums import ChildSessionEndReason, CuriosityDomain
from app.domain.models.base import UserHash
from app.domain.models.child_session import ChildSession
from app.domain.models.learner import LearnerId
from app.domain.models.writes import ChildSessionEnd, ChildSessionStart, ChildTalkTurn
from app.store.tables import child_sessions, learners


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
        )

    @staticmethod
    async def last_ended_at(session: AsyncSession, user_hash: UserHash) -> datetime | None:
        ended: datetime | None = (
            await session.execute(
                select(func.max(child_sessions.c.ended_at)).where(
                    child_sessions.c.user_hash == user_hash
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
        EXPIRED; their summary waits for a turn-less sender (nudges)."""
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


def _open_session(owner: UserHash, session_id: UUID) -> ColumnElement[bool]:
    return and_(
        child_sessions.c.id == session_id,
        child_sessions.c.user_hash == owner,
        child_sessions.c.ended_at.is_(None),
    )
