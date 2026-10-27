"""MediaBlobRepository: reply audio kept until the sender uploads it (s06 §4.7, §4.8).

Reply audio is saved after safety_out passes, in its own short transaction, and expires after
24 hours; the maintenance pass deletes what has expired. WhatsApp voice notes from users are
never stored here (data-model §4).
"""

from datetime import timedelta
from typing import ClassVar
from uuid import UUID, uuid4

from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import MediaTooLarge, StoreError
from app.domain.enums import MediaPurpose
from app.domain.models.base import UserHash
from app.domain.models.message import AudioClip
from app.store.tables import MEDIA_BLOB_MAX_BYTES, media_blobs


class MediaBlobRepository:
    """Satisfies `ReplyAudioStore`."""

    REPLY_AUDIO_LIFETIME: ClassVar[timedelta] = timedelta(hours=24)

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, user_hash: UserHash, clip: AudioClip) -> UUID:
        """Raises MediaTooLarge over 2 MB (the reply then goes as text only)."""
        size = len(clip.data)
        if size > MEDIA_BLOB_MAX_BYTES:
            raise MediaTooLarge(f"reply audio is {size} bytes")
        blob_id = uuid4()
        statement = insert(media_blobs).values(
            id=blob_id,
            user_hash=user_hash,
            purpose=MediaPurpose.REPLY_AUDIO.value,
            mime_type=clip.mime_type,
            data=clip.data,
            size_bytes=size,
            expires_at=func.now() + self.REPLY_AUDIO_LIFETIME,
        )
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(statement)
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not save reply audio: {type(exc).__name__}") from exc
        return blob_id

    async def load_audio(self, blob_id: UUID) -> AudioClip | None:
        """The clip, or None when it has expired and been deleted."""
        statement = select(media_blobs.c.data, media_blobs.c.mime_type).where(
            media_blobs.c.id == blob_id, media_blobs.c.expires_at > func.now()
        )
        try:
            async with self._session_factory() as session:
                row = (await session.execute(statement)).first()
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not load media: {type(exc).__name__}") from exc
        if row is None:
            return None
        return AudioClip(data=row.data, mime_type=row.mime_type, duration_ms=None)

    async def delete_expired(self) -> int:
        statement = delete(media_blobs).where(media_blobs.c.expires_at <= func.now())
        try:
            async with self._session_factory() as session, session.begin():
                result = await session.execute(statement.returning(media_blobs.c.id))
                return len(result.all())
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not delete expired media: {type(exc).__name__}") from exc
