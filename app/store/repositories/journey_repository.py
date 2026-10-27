"""The khoj offered to each child and how it went (s10b §5, data-model `learner_activities`).

Writes run inside the finalize transaction, and only for the user's own learners: an id that
belongs to someone else changes nothing.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import StoreError
from app.domain.enums import ActivityStatus
from app.domain.models.activity import OfferRecord
from app.domain.models.base import TurnId, UserHash
from app.domain.models.learner import LearnerId
from app.domain.models.writes import ActivityOffered, ActivityReported
from app.store.tables import learner_activities, learners


class JourneyRepository:
    HISTORY_WINDOW: timedelta = timedelta(days=60)
    HISTORY_LIMIT: int = 90  # enough for 30 per child, the repeat window

    @staticmethod
    async def record_offer(
        session: AsyncSession, owner: UserHash, turn_id: TurnId, write: ActivityOffered
    ) -> None:
        owned = await JourneyRepository._owns(session, owner, write.learner_id)
        if not owned:
            raise StoreError("an activity can only be offered to the user's own learner")
        await session.execute(
            insert(learner_activities).values(
                id=write.learner_activity_id,
                learner_id=write.learner_id,
                activity_id=write.activity_id,
                activity_version=write.activity_version,
                offered_turn_id=turn_id,
                status=ActivityStatus.OFFERED.value,
            )
        )

    @staticmethod
    async def record_report(
        session: AsyncSession, owner: UserHash, write: ActivityReported
    ) -> None:
        owned_learners = select(learners.c.id).where(learners.c.owner_user_hash == owner)
        await session.execute(
            update(learner_activities)
            .where(
                and_(
                    learner_activities.c.id == write.learner_activity_id,
                    learner_activities.c.learner_id.in_(owned_learners),
                )
            )
            .values(
                status=write.status.value,
                child_response_summary=write.summary,
                reported_at=func.now(),
            )
        )

    @staticmethod
    async def recent_for(
        session: AsyncSession, learner_ids: Sequence[LearnerId], now: datetime
    ) -> list[OfferRecord]:
        """These learners' activities in the last 60 days, newest first."""
        if not learner_ids:
            return []
        rows = (
            await session.execute(
                select(learner_activities)
                .where(
                    and_(
                        learner_activities.c.learner_id.in_(learner_ids),
                        learner_activities.c.offered_at > now - JourneyRepository.HISTORY_WINDOW,
                    )
                )
                .order_by(learner_activities.c.offered_at.desc(), learner_activities.c.id)
                .limit(JourneyRepository.HISTORY_LIMIT)
            )
        ).all()
        return [
            OfferRecord(
                learner_activity_id=row.id,
                learner_id=LearnerId(row.learner_id),
                activity_id=row.activity_id,
                activity_version=row.activity_version,
                offered_at=row.offered_at,
                status=ActivityStatus(row.status),
            )
            for row in rows
        ]

    @staticmethod
    async def _owns(session: AsyncSession, owner: UserHash, learner_id: LearnerId) -> bool:
        found = await session.execute(
            select(learners.c.id).where(
                and_(learners.c.id == learner_id, learners.c.owner_user_hash == owner)
            )
        )
        return found.first() is not None
