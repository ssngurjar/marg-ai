"""Curiosity signals: what a child engaged with on a journey turn (s13 §4.4, data-model).

Saved after the reply, in its own short transaction, once per turn: a retried task can't
double-count. If the user was deleted meanwhile, nothing is saved.
"""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import StoreError
from app.core.logging import get_logger
from app.domain.enums import ActivityStatus, CuriosityDomain
from app.domain.models.curiosity import CuriositySignals, ExtractSignals
from app.domain.models.learner import LearnerId
from app.domain.rules.curiosity_trajectory import (
    CuriosityPoint,
    CuriosityTrajectory,
    YoungLearnerTrajectory,
)
from app.store.tables import curiosity_signals, learner_activities, turns

logger = get_logger(__name__)


class CuriositySignalRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(
        self, task: ExtractSignals, signals: CuriositySignals, prompt_version: str
    ) -> bool:
        """False when the turn or child no longer exists (deleted before this ran)."""
        statement = (
            insert(curiosity_signals)
            .values(
                turn_id=task.turn_id,
                learner_id=task.learner_id,
                source=task.source.kind,
                domains=[domain.value for domain in signals.domains],
                engagement=signals.engagement,
                child_asked_question=signals.child_asked_question,
                prompt_version=prompt_version,
            )
            .on_conflict_do_nothing(index_elements=["turn_id"])
        )
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(statement)
        except IntegrityError as exc:  # a foreign key: the user (and turn and child) is gone
            logger.warning("curiosity_signals_user_gone", turn_id=str(task.turn_id), exc_info=exc)
            return False
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not save curiosity signals: {type(exc).__name__}") from exc
        return True

    async def trajectory_for(self, learner_id: LearnerId) -> YoungLearnerTrajectory:
        """The child's curiosity over time (s13 §4.5): every signal, with when its turn began,
        and how many activities were offered and done."""
        points_query = (
            select(
                turns.c.started_at,
                curiosity_signals.c.domains,
                curiosity_signals.c.engagement,
                curiosity_signals.c.child_asked_question,
            )
            .join(turns, turns.c.id == curiosity_signals.c.turn_id)
            .where(curiosity_signals.c.learner_id == learner_id)
        )
        counts_query = select(
            func.count(),
            func.count().filter(learner_activities.c.status == ActivityStatus.DONE.value),
        ).where(learner_activities.c.learner_id == learner_id)
        try:
            async with self._session_factory() as session:
                rows = (await session.execute(points_query)).all()
                offered, done = (await session.execute(counts_query)).one()
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not read a trajectory: {type(exc).__name__}") from exc
        points = [
            CuriosityPoint(
                at=row.started_at,
                domains=frozenset(CuriosityDomain(domain) for domain in row.domains),
                engagement=row.engagement,
                child_asked_question=row.child_asked_question,
            )
            for row in rows
        ]
        return CuriosityTrajectory.of(points, offered=int(offered), done=int(done))
