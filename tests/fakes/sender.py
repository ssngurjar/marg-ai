"""A ChannelSender that records what it was asked to send and fails on demand."""

from collections.abc import Callable
from dataclasses import dataclass

from app.core.errors import ProviderError
from app.domain.enums import Channel
from app.domain.models.message import AudioClip, ImageClip
from app.domain.models.reply import OutboundPart
from app.providers.ports import ChannelAddress, DeliveryReceipt
from tests.fakes.clock import FixedClock


@dataclass(frozen=True, slots=True)
class SentPart:
    part: OutboundPart
    address: str
    audio: AudioClip | None = None


class FakeSender:
    """Satisfies `ChannelSender`. `fail_with` decides, per call, whether to raise instead."""

    channel: Channel = Channel.WHATSAPP

    def __init__(
        self,
        clock: FixedClock,
        fail_with: Callable[[OutboundPart, int], ProviderError | None] | None = None,
        acknowledge_error: ProviderError | None = None,
    ) -> None:
        self.sent: list[SentPart] = []
        self.acknowledged: list[str] = []
        self.calls = 0
        self._clock = clock
        self._fail_with = fail_with
        self._acknowledge_error = acknowledge_error

    async def send(
        self,
        part: OutboundPart,
        recipient: ChannelAddress,
        audio: AudioClip | None = None,
        image: ImageClip | None = None,
    ) -> DeliveryReceipt:
        self.calls += 1
        error = self._fail_with(part, self.calls) if self._fail_with else None
        if error is not None:
            raise error
        self.sent.append(SentPart(part, recipient.address.get_secret_value(), audio))
        return DeliveryReceipt(
            provider_message_id=f"wamid.FAKE{len(self.sent)}", sent_at=self._clock.now()
        )

    async def acknowledge(self, external_id: str) -> None:
        self.acknowledged.append(external_id)
        if self._acknowledge_error is not None:
            raise self._acknowledge_error
