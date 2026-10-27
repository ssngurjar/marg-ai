"""Protocols the pipeline and layers depend on (contracts.md §3).

Each step adds the ports it introduces. Adapters implement them; tests use fakes from tests/fakes.
The `Clock` protocol lives in app/core/clock.py (core infrastructure, importable by every layer).
"""

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, SecretStr

from app.domain.enums import Channel
from app.domain.models.message import AudioClip, ImageClip
from app.domain.models.reply import OutboundPart


class ChannelAddress(BaseModel):
    """Where a part goes. Decrypted only inside the sender, never logged."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: Channel
    address: SecretStr  # wa_id digits for WhatsApp; user_hash for web


class DeliveryReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_message_id: str | None  # wamid for WhatsApp; None for web
    sent_at: datetime


class ChannelSender(Protocol):
    channel: Channel

    async def send(
        self,
        part: OutboundPart,
        recipient: ChannelAddress,
        audio: AudioClip | None = None,
        image: ImageClip | None = None,
    ) -> DeliveryReceipt: ...

    async def acknowledge(self, external_id: str) -> None:
        """WhatsApp: mark read and show "typing…". Web: nothing."""
        ...
