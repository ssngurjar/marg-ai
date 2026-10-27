"""WebSender: delivery to a web demo visitor (s14 §4.8).

There's no external call: the page polls for its turn and reads the parts from the outbox, so
"sending" is the outbox marking the part sent. Web parts follow the same order, retry and
failure rules as WhatsApp parts: one code path.
"""

from app.core.clock import Clock
from app.domain.enums import Channel
from app.domain.models.message import AudioClip, ImageClip
from app.domain.models.reply import OutboundPart
from app.providers.ports import ChannelAddress, DeliveryReceipt


class WebSender:
    """Satisfies `ChannelSender` for Channel.WEB."""

    channel: Channel = Channel.WEB

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    async def send(
        self,
        part: OutboundPart,
        recipient: ChannelAddress,
        audio: AudioClip | None = None,
        image: ImageClip | None = None,
    ) -> DeliveryReceipt:
        if recipient.channel is not Channel.WEB:
            raise ValueError(f"WebSender can't send to a {recipient.channel} address")
        return DeliveryReceipt(provider_message_id=None, sent_at=self._clock.now())

    async def acknowledge(self, external_id: str) -> None:
        """Nothing to do: the page's trace already shows the turn's progress."""
