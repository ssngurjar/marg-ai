"""Khoj cards: the image, its link to the report, and the KHOJ_CARD turn that sends it
(s10b §4.13, C6). One transaction, so a card is either fully queued or not at all.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import MediaTooLarge, StoreError
from app.domain.enums import Channel, Language, MediaPurpose, Route, TurnStatus
from app.domain.models.base import TurnId, UserHash
from app.domain.models.learner import LearnerId
from app.domain.models.message import ImageClip
from app.pipeline.reply_parts_builder import ReplyDelivery
from app.store.repositories.outbox_repository import OutboxRepository
from app.store.tables import (
    MEDIA_BLOB_MAX_BYTES,
    learner_activities,
    learners,
    media_blobs,
    turns,
    users,
)
from app.store.turn_progress_notifier import TurnProgressNotifier


@dataclass(frozen=True, slots=True)
class QueuedCard:
    """Everything one card turn writes."""

    learner_activity_id: UUID
    image_blob_id: UUID  # chosen before the delivery is built, which refers to it
    image: ImageClip
    delivery: ReplyDelivery  # one IMAGE part, its caption sealed by safety
    caption: str
    register: Language
    worker_id: str


class KhojCardRepository:
    CARD_LIFETIME: ClassVar[timedelta] = timedelta(days=7)

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def new_blob_id() -> UUID:
        return uuid4()

    async def card_since(self, learner_id: LearnerId, since: datetime) -> bool:
        """At most one card per child per day (s10b §4.13)."""
        statement = (
            select(learner_activities.c.id)
            .join(media_blobs, media_blobs.c.id == learner_activities.c.card_blob_id)
            .where(
                and_(
                    learner_activities.c.learner_id == learner_id,
                    media_blobs.c.created_at >= since,
                )
            )
            .limit(1)
        )
        try:
            async with self._session_factory() as session:
                return (await session.execute(statement)).first() is not None
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not check today's cards: {type(exc).__name__}") from exc

    async def queue(self, card: QueuedCard) -> TurnId | None:
        """Store the image, link it to the report, and queue the card turn. None when the
        report (or its user) no longer exists. Raises MediaTooLarge over 2 MB."""
        size = len(card.image.data)
        if size > MEDIA_BLOB_MAX_BYTES:
            raise MediaTooLarge(f"khoj card is {size} bytes")
        try:
            async with self._session_factory() as session, session.begin():
                recipient = await _owner_of(session, card.learner_activity_id)
                if recipient is None:
                    return None
                owner = recipient.user_hash
                await session.execute(
                    media_blobs.insert().values(
                        id=card.image_blob_id,
                        user_hash=owner,
                        purpose=MediaPurpose.KHOJ_CARD.value,
                        mime_type=card.image.mime_type,
                        data=card.image.data,
                        size_bytes=size,
                        expires_at=func.now() + self.CARD_LIFETIME,
                    )
                )
                await session.execute(
                    update(learner_activities)
                    .where(learner_activities.c.id == card.learner_activity_id)
                    .values(card_blob_id=card.image_blob_id)
                )
                turn_id = TurnId(uuid4())
                await session.execute(
                    turns.insert().values(
                        id=turn_id,
                        user_hash=owner,
                        status=TurnStatus.COMPLETED.value,
                        route=Route.KHOJ_CARD.value,
                        reply_text=card.caption,
                        reply_register=card.register.value,
                        worker_id=card.worker_id,
                        completed_at=func.now(),
                    )
                )
                # The parent's own channel: a web visitor's card goes to their page (s14).
                await OutboxRepository.enqueue(
                    session, turn_id, owner, recipient.channel, card.delivery
                )
                await TurnProgressNotifier.notify(session, turn_id)
                return turn_id
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not queue a khoj card: {type(exc).__name__}") from exc


@dataclass(frozen=True, slots=True)
class _Recipient:
    user_hash: UserHash
    channel: Channel


async def _owner_of(session: AsyncSession, learner_activity_id: UUID) -> _Recipient | None:
    row = (
        await session.execute(
            select(users.c.user_hash, users.c.channel)
            .join(learners, learners.c.owner_user_hash == users.c.user_hash)
            .join(learner_activities, learner_activities.c.learner_id == learners.c.id)
            .where(learner_activities.c.id == learner_activity_id)
        )
    ).first()
    if row is None:
        return None
    return _Recipient(user_hash=UserHash(row.user_hash), channel=Channel(row.channel))
