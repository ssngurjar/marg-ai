"""Core domain models (contracts.md §2.1). Frozen; unknown fields are rejected."""

from datetime import datetime
from typing import NewType, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.enums import Channel, MessageKind

UserHash = NewType("UserHash", str)
"""64 lowercase hex chars: HMAC-SHA256(USER_HASH_SALT, "<channel>:<address>")."""


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


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
