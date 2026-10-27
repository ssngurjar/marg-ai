"""MediaBlobRepository: reply audio kept until the sender uploads it (s06 §4.7, §4.8).

Reply audio is saved after safety_out passes, in its own short transaction, and expires after
24 hours; the maintenance pass deletes what has expired. WhatsApp voice notes from users are
never stored here (data-model §4).
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import timedelta
from typing import ClassVar
from uuid import UUID, uuid4

from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import MediaTooLarge, MediaUnsupported, StoreError
from app.domain.enums import MediaPurpose
from app.domain.models.base import UserHash
from app.domain.models.message import AudioClip, ImageClip, MediaRef
from app.store.tables import MEDIA_BLOB_MAX_BYTES, media_blobs


@dataclass(frozen=True, slots=True)
class OwnedMedia:
    data: bytes
    mime_type: str


class MediaBlobRepository:
    """Satisfies `ReplyAudioStore`, `ReplyImageStore`, and `MediaFetcher` for web voice notes."""

    REPLY_AUDIO_LIFETIME: ClassVar[timedelta] = timedelta(hours=24)
    INBOUND_AUDIO_LIFETIME: ClassVar[timedelta] = timedelta(hours=24)  # if no turn ever hears it

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

    async def load_image(self, blob_id: UUID) -> ImageClip | None:
        """A khoj card's image, or None when it has expired and been deleted."""
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
        return ImageClip(data=row.data, mime_type=row.mime_type)

    async def save_inbound_audio(self, user_hash: UserHash, clip: AudioClip) -> UUID:
        """A web visitor's voice note, until its turn has heard it (S14)."""
        size = len(clip.data)
        if size > MEDIA_BLOB_MAX_BYTES:
            raise MediaTooLarge(f"voice note is {size} bytes")
        blob_id = uuid4()
        statement = insert(media_blobs).values(
            id=blob_id,
            user_hash=user_hash,
            purpose=MediaPurpose.INBOUND_AUDIO.value,
            mime_type=clip.mime_type,
            data=clip.data,
            size_bytes=size,
            expires_at=func.now() + self.INBOUND_AUDIO_LIFETIME,
        )
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(statement)
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not save a voice note: {type(exc).__name__}") from exc
        return blob_id

    async def fetch(self, ref: MediaRef) -> AudioClip:
        """`MediaFetcher` for web voice notes. Raises MediaUnsupported when it's gone."""
        if ref.blob_id is None:
            raise ValueError("MediaBlobRepository.fetch needs a stored blob")
        audio = await self.load_audio(ref.blob_id)
        if audio is None:
            raise MediaUnsupported("the voice note has expired")
        return audio.model_copy(update={"mime_type": ref.mime_type})

    async def owned(
        self, user_hash: UserHash, blob_id: UUID, purposes: Collection[MediaPurpose]
    ) -> OwnedMedia | None:
        """Reply audio or a card for the page: only the owner's, unexpired, of these purposes."""
        statement = select(media_blobs.c.data, media_blobs.c.mime_type).where(
            media_blobs.c.id == blob_id,
            media_blobs.c.user_hash == user_hash,
            media_blobs.c.purpose.in_([purpose.value for purpose in purposes]),
            media_blobs.c.expires_at > func.now(),
        )
        try:
            async with self._session_factory() as session:
                row = (await session.execute(statement)).first()
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not load media: {type(exc).__name__}") from exc
        return OwnedMedia(data=row.data, mime_type=row.mime_type) if row else None

    @staticmethod
    async def delete_inbound(session: AsyncSession, owner: UserHash, blob_id: UUID) -> None:
        """Inside finalize: the voice note was heard; it isn't kept (CLAUDE.md §11)."""
        await session.execute(
            delete(media_blobs).where(
                media_blobs.c.id == blob_id,
                media_blobs.c.user_hash == owner,
                media_blobs.c.purpose == MediaPurpose.INBOUND_AUDIO.value,
            )
        )

    async def delete_expired(self) -> int:
        statement = delete(media_blobs).where(media_blobs.c.expires_at <= func.now())
        try:
            async with self._session_factory() as session, session.begin():
                result = await session.execute(statement.returning(media_blobs.c.id))
                return len(result.all())
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not delete expired media: {type(exc).__name__}") from exc
