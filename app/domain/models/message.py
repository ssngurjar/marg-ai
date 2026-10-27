"""What users send us: messages and the media they carry (contracts.md §2.1)."""

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import model_validator

from app.domain.enums import Channel, Language, MessageKind
from app.domain.models.base import DomainModel, UserHash


class MediaRef(DomainModel):
    """Where a piece of inbound media lives: exactly one of a provider id or a stored blob."""

    channel: Channel
    provider_media_id: str | None
    blob_id: UUID | None
    mime_type: str

    @model_validator(mode="after")
    def _exactly_one_location(self) -> Self:
        if (self.provider_media_id is None) == (self.blob_id is None):
            raise ValueError("exactly one of provider_media_id and blob_id must be set")
        return self


class InboundMessage(DomainModel):
    channel: Channel
    external_id: str  # wamid.* or a web-generated uuid
    user_hash: UserHash
    kind: MessageKind
    text: str | None  # TEXT, the button title for INTERACTIVE, or an image caption
    media: MediaRef | None  # AUDIO, IMAGE
    interactive_reply_id: str | None  # a button or list id we issued, or a template payload
    provider_sent_at: datetime  # when the user sent it
    received_at: datetime  # when we stored it


class AudioClip(DomainModel):
    data: bytes
    mime_type: str  # "audio/ogg; codecs=opus", "audio/wav", "audio/webm", "audio/mp4"
    duration_ms: int | None


class ImageClip(DomainModel):
    """Photos (memory only, never persisted) and khoj cards."""

    data: bytes
    mime_type: str  # "image/jpeg", "image/png", "image/webp"


class Transcript(DomainModel):
    """What a voice note said (contracts §2.1). Muse Voice Transcribe returns no language or
    confidence: the language comes from RegisterDetector, and confidence is None."""

    text: str
    language: Language | None
    confidence: float | None
    audio_duration_ms: int
