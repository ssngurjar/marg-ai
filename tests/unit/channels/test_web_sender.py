"""WebSender and ChannelMediaFetcher: the web channel's delivery and voice notes (s14)."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.channels.web.web_sender import WebSender
from app.core.errors import MediaUnsupported
from app.domain.enums import Channel, PartKind
from app.domain.models.message import AudioClip, MediaRef
from app.domain.models.reply import OutboundPart
from app.pipeline.channel_media_fetcher import ChannelMediaFetcher
from app.providers.ports import ChannelAddress
from tests.fakes.clock import FixedClock
from tests.fakes.voice import FakeMediaFetcher

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
PART = OutboundPart(
    part_no=0, kind=PartKind.TEXT, text="Namaste", audio_blob_id=None, image_blob_id=None,
    buttons=[], template=None,
)  # fmt: skip


async def test_a_web_part_is_delivered_at_once_with_no_provider_id() -> None:
    receipt = await WebSender(FixedClock(NOW)).send(
        PART, ChannelAddress(channel=Channel.WEB, address=SecretStr("hash"))
    )
    assert (receipt.provider_message_id, receipt.sent_at) == (None, NOW)


async def test_a_whatsapp_address_is_a_bug() -> None:
    with pytest.raises(ValueError, match="can't send to a whatsapp address"):
        await WebSender(FixedClock(NOW)).send(
            PART, ChannelAddress(channel=Channel.WHATSAPP, address=SecretStr("919000000001"))
        )


async def test_media_is_fetched_from_its_own_channel() -> None:
    whatsapp, web = FakeMediaFetcher(), FakeMediaFetcher()
    fetcher = ChannelMediaFetcher({Channel.WHATSAPP: whatsapp, Channel.WEB: web})
    ref = MediaRef(
        channel=Channel.WEB, provider_media_id=None, blob_id=uuid4(), mime_type="audio/webm"
    )
    clip = await fetcher.fetch(ref)
    assert isinstance(clip, AudioClip)
    assert web.refs == [ref]
    assert whatsapp.refs == []


async def test_a_channel_without_a_fetcher_is_unsupported() -> None:
    fetcher = ChannelMediaFetcher({Channel.WHATSAPP: FakeMediaFetcher()})
    ref = MediaRef(
        channel=Channel.WEB, provider_media_id=None, blob_id=uuid4(), mime_type="audio/webm"
    )
    with pytest.raises(MediaUnsupported, match="no media fetcher for web"):
        await fetcher.fetch(ref)
