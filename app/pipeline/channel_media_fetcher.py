"""ChannelMediaFetcher: a voice note or photo from wherever its channel keeps it (s06 §4.2,
s10b §4.14, s14).

WhatsApp media is downloaded from Meta; a web voice note or photo was stored by the demo API.
Satisfies `MediaFetcher` by handing each ref to the fetcher for its channel.
"""

from collections.abc import Mapping

from app.core.errors import MediaUnsupported
from app.domain.enums import Channel
from app.domain.models.message import AudioClip, ImageClip, MediaRef
from app.providers.ports import MediaFetcher


class ChannelMediaFetcher:
    def __init__(self, by_channel: Mapping[Channel, MediaFetcher]) -> None:
        self._by_channel = dict(by_channel)

    async def fetch(self, ref: MediaRef) -> AudioClip:
        return await self._fetcher_for(ref).fetch(ref)

    async def fetch_image(self, ref: MediaRef) -> ImageClip:
        return await self._fetcher_for(ref).fetch_image(ref)

    def _fetcher_for(self, ref: MediaRef) -> MediaFetcher:
        fetcher = self._by_channel.get(ref.channel)
        if fetcher is None:
            raise MediaUnsupported(f"no media fetcher for {ref.channel.value}")
        return fetcher
