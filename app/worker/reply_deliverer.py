"""Sending a turn's queued parts, in order, with retries (s04 §4.10; E1: sent directly).

The rules for order and backoff live in DeliveryPlanner (app/domain/rules). A retryable
failure leaves the part pending with a retry time; the dispatcher's maintenance pass sends it
when it's due. Nothing here logs message content or phone numbers.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from pydantic import SecretStr

from app.constants.whatsapp import CUSTOMER_SERVICE_WINDOW
from app.core.clock import Clock
from app.core.errors import InvalidAddressCiphertext, ProviderError
from app.core.logging import get_logger
from app.core.user_identity import UserIdentity
from app.domain.enums import Channel, PartKind
from app.domain.models.base import TurnId
from app.domain.models.message import AudioClip, ImageClip
from app.domain.rules.delivery_planner import DeliveryPlanner
from app.providers.http import RetryPolicy
from app.providers.ports import ChannelAddress, ChannelSender, ReplyAudioStore, ReplyImageStore
from app.store.repositories.outbox_repository import OutboxRepository, OutboxRow
from app.store.repositories.user_repository import UserRepository

ERROR_TEXT_LIMIT: Final = 200

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DeliverySettings:
    max_attempts: int  # OUTBOX_MAX_ATTEMPTS
    part_budget: timedelta  # how long one part's send, with its retries, may take


@dataclass(frozen=True, slots=True)
class DeliveryDeps:
    outbox: OutboxRepository
    users: UserRepository
    senders: Mapping[Channel, ChannelSender]
    identity: UserIdentity
    retry: RetryPolicy
    clock: Clock
    audio: ReplyAudioStore  # reply voice notes (s06 §4.8)
    images: ReplyImageStore  # khoj cards (s10b §4.13)


@dataclass(frozen=True, slots=True)
class _PartMedia:
    audio: AudioClip | None = None
    image: ImageClip | None = None


class ReplyDeliverer:
    def __init__(self, deps: DeliveryDeps, settings: DeliverySettings) -> None:
        self._outbox = deps.outbox
        self._users = deps.users
        self._senders = deps.senders
        self._identity = deps.identity
        self._retry = deps.retry
        self._clock = deps.clock
        self._audio = deps.audio
        self._images = deps.images
        self._settings = settings

    async def deliver_turn(self, turn_id: TurnId) -> int:
        """Send this turn's due parts in order until one has to wait. Returns how many were sent.

        If the user asked for their data to be deleted in this turn and no part is left to send,
        they are purged now (s08 §4.10): the confirmation went out first.
        """
        sent = 0
        while (row := await self._outbox.claim_next_part(turn_id)) is not None:
            if await self._send(row):
                sent += 1
        if await self._users.purge_if_delivered(turn_id):
            logger.info("user_purged", turn_id=str(turn_id))
        return sent

    async def _send(self, row: OutboxRow) -> bool:
        sender = self._senders.get(row.channel)
        if sender is None:
            await self._fail(row, "no_sender_for_channel")
            return False
        if self._window_closed(row):
            await self._fail(row, "window_closed")
            return False
        media = await self._media_for(row)
        if media is None:
            return False
        try:
            recipient = self._recipient(row)
        except InvalidAddressCiphertext as exc:
            await self._fail(row, type(exc).__name__)
            return False
        deadline = self._clock.now() + self._settings.part_budget
        try:
            receipt = await self._retry.run(
                lambda: sender.send(row.part, recipient, audio=media.audio, image=media.image),
                deadline=deadline,
            )
        except ProviderError as exc:
            await self._handle_provider_error(row, exc)
            return False
        await self._outbox.mark_sent(row.outbox_id, receipt.provider_message_id, receipt.sent_at)
        return True

    async def _media_for(self, row: OutboxRow) -> "_PartMedia | None":
        """The media the part carries; None (and the part failed) when it can't be loaded. A
        StoreError propagates, as it does from the outbox's own calls."""
        if row.part.kind is PartKind.IMAGE:
            image_id = row.part.image_blob_id  # None once the blob was deleted (SET NULL)
            image = await self._images.load_image(image_id) if image_id is not None else None
            if image is None:
                await self._fail(row, "media_expired")
                return None
            return _PartMedia(image=image)
        if row.part.kind is not PartKind.AUDIO:
            return _PartMedia()
        blob_id = row.part.audio_blob_id  # None once the blob was deleted (SET NULL)
        audio = await self._audio.load_audio(blob_id) if blob_id is not None else None
        if audio is None:
            await self._fail(row, "media_expired")
            return None
        return _PartMedia(audio=audio)

    def _window_closed(self, row: OutboxRow) -> bool:
        if row.channel is not Channel.WHATSAPP or row.part.kind is PartKind.TEMPLATE:
            return False  # templates are the one kind Meta delivers outside the window
        if row.last_inbound_at is None:
            return True
        return self._clock.now() - row.last_inbound_at > CUSTOMER_SERVICE_WINDOW

    def _recipient(self, row: OutboxRow) -> ChannelAddress:
        if row.channel is Channel.WHATSAPP:
            if row.address_ciphertext is None:
                raise InvalidAddressCiphertext("the user has no stored WhatsApp address")
            address = self._identity.decrypt_address(row.user_hash, row.address_ciphertext)
            return ChannelAddress(channel=Channel.WHATSAPP, address=address)
        # The web channel addresses a session by its user hash (s04 §4.10, s14).
        return ChannelAddress(channel=Channel.WEB, address=SecretStr(row.user_hash))

    async def _handle_provider_error(self, row: OutboxRow, error: ProviderError) -> None:
        code = _error_code(error)
        if error.retryable and row.attempts < self._settings.max_attempts:
            await self._outbox.mark_retry(
                row.outbox_id, code, DeliveryPlanner.retry_delay(row.attempts)
            )
            logger.warning(
                "delivery_retry_scheduled",
                outbox_id=row.outbox_id,
                attempts=row.attempts,
                error=code,
            )
            return
        await self._fail(row, code)

    async def _fail(self, row: OutboxRow, code: str) -> None:
        await self._outbox.mark_failed(row.outbox_id, code)
        logger.error(
            "delivery_failed",
            outbox_id=row.outbox_id,
            turn_id=str(row.turn_id),
            part_no=row.part.part_no,
            error=code,
        )


def _error_code(error: ProviderError) -> str:
    """A short, PII-free description: the error type and the provider's own message."""
    return f"{type(error).__name__}: {error}"[:ERROR_TEXT_LIMIT]
