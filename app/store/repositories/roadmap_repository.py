"""RoadmapRepository: a student's plan (s12 §4.4; data-model `roadmaps`, `roadmap_steps`).

A roadmap is only ever written by a `SaveRoadmap` write, inside the turn's finalize transaction
with its outbox rows, so a reply that safety blocked never leaves a plan the student didn't
see. Saving abandons the student's active plan first; the partial unique index guarantees one
active plan even under a race.
"""

from uuid import UUID, uuid4

from pydantic import HttpUrl
from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import RoadmapStatus, RoadmapStepStatus
from app.domain.models.base import UserHash
from app.domain.models.student import Roadmap, RoadmapStep
from app.domain.models.writes import SaveRoadmap
from app.store.tables import roadmap_steps, roadmaps


class RoadmapRepository:
    @staticmethod
    async def active_for(session: AsyncSession, user_hash: UserHash) -> Roadmap | None:
        row = (
            await session.execute(
                select(roadmaps).where(
                    and_(
                        roadmaps.c.user_hash == user_hash,
                        roadmaps.c.status == RoadmapStatus.ACTIVE.value,
                    )
                )
            )
        ).first()
        if row is None:
            return None
        step_rows = (
            await session.execute(
                select(roadmap_steps)
                .where(roadmap_steps.c.roadmap_id == row.id)
                .order_by(roadmap_steps.c.position)
            )
        ).all()
        steps = [
            RoadmapStep(
                position=step.position,
                action=step.action,
                timeframe=step.timeframe,
                cost_inr=step.cost_inr,
                source_url=HttpUrl(step.source_url) if step.source_url else None,
                status=RoadmapStepStatus(step.status),
            )
            for step in step_rows
        ]
        return Roadmap(
            id=row.id,
            goal=row.goal,
            status=RoadmapStatus(row.status),
            steps=steps,
            created_at=row.created_at,
        )

    @staticmethod
    async def save(session: AsyncSession, owner: UserHash, write: SaveRoadmap) -> UUID:
        """Inside finalize: abandon the owner's active plan, then store the new one."""
        await session.execute(
            update(roadmaps)
            .where(
                and_(
                    roadmaps.c.user_hash == owner,
                    roadmaps.c.status == RoadmapStatus.ACTIVE.value,
                )
            )
            .values(status=RoadmapStatus.ABANDONED.value, updated_at=func.now())
        )
        roadmap_id = uuid4()
        await session.execute(
            insert(roadmaps).values(
                id=roadmap_id,
                user_hash=owner,
                goal=write.goal,
                status=RoadmapStatus.ACTIVE.value,
                prompt_version=write.prompt_version,
            )
        )
        for position, step in enumerate(write.steps, start=1):
            await session.execute(
                insert(roadmap_steps).values(
                    id=uuid4(),
                    roadmap_id=roadmap_id,
                    position=position,
                    action=step.action,
                    timeframe=step.timeframe,
                    cost_inr=step.cost_inr,
                    source_url=str(step.source_url) if step.source_url else None,
                    status=RoadmapStepStatus.TODO.value,
                )
            )
        return roadmap_id
