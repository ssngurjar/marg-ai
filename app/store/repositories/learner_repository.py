"""Learners: a parent's children or a student's own learner (s08 §4.11, data-model `learners`)."""

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidProfileValue
from app.domain.enums import LearnerRelation
from app.domain.models.base import UserHash
from app.domain.models.learner import Learner, LearnerId
from app.domain.models.writes import ChildTalkConsent, LearnerUpsert
from app.domain.rules.conversation_machine import MAX_LEARNERS
from app.store.tables import learners, users


class LearnerRepository:
    @staticmethod
    async def upsert(session: AsyncSession, owner: UserHash, write: LearnerUpsert) -> None:
        """Inside finalize. Holds the owner's row lock while counting, so two turns can't both
        add a third child. A fourth is a bug (the state machine checks first)."""
        await session.execute(
            select(users.c.user_hash).where(users.c.user_hash == owner).with_for_update()
        )
        count = (
            await session.execute(
                select(func.count())
                .select_from(learners)
                .where(
                    and_(
                        learners.c.owner_user_hash == owner,
                        learners.c.id != write.learner_id,
                    )
                )
            )
        ).scalar_one()
        if count >= MAX_LEARNERS:
            raise InvalidProfileValue(f"an owner may have at most {MAX_LEARNERS} learners")
        statement = insert(learners).values(
            id=write.learner_id,
            owner_user_hash=owner,
            relation=write.relation.value,
            nickname=write.nickname,
            birth_year=write.birth_year,
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[learners.c.id],
                set_={
                    "nickname": statement.excluded.nickname,
                    "birth_year": statement.excluded.birth_year,
                    "updated_at": func.now(),
                },
                where=learners.c.owner_user_hash == owner,
            )
        )

    @staticmethod
    async def set_child_talk(
        session: AsyncSession, owner: UserHash, write: ChildTalkConsent
    ) -> None:
        """Inside finalize: the parent's consent for direct child talk (C13), or its revoke."""
        await session.execute(
            update(learners)
            .where(and_(learners.c.id == write.learner_id, learners.c.owner_user_hash == owner))
            .values(
                child_talk_consented_at=func.now() if write.granted else None,
                updated_at=func.now(),
            )
        )

    @staticmethod
    async def list_for(session: AsyncSession, owner: UserHash) -> list[Learner]:
        rows = (
            await session.execute(
                select(learners)
                .where(learners.c.owner_user_hash == owner)
                .order_by(learners.c.created_at, learners.c.id)
            )
        ).all()
        return [
            Learner(
                id=LearnerId(row.id),
                relation=LearnerRelation(row.relation),
                nickname=row.nickname,
                birth_year=row.birth_year,
                child_talk_consented_at=row.child_talk_consented_at,
            )
            for row in rows
        ]
