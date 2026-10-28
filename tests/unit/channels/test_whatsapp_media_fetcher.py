"""WhatsAppMediaFetcher: the two-step voice-note download (s06 §4.2, §9)."""

import hashlib
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.channels.whatsapp.whatsapp_media_fetcher import MediaFetchConfig, WhatsAppMediaFetcher
from app.core.errors import (
    MediaTooLarge,
    MediaUnsupported,
    ProviderRateLimited,
    ProviderRejected,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.domain.enums import Channel
from app.domain.models.message import MediaRef
from app.providers.http import RetryPolicy, RetryTiming
from tests.fakes.clock import FixedClock
from tests.fakes.sleeper import FakeSleeper

pytestmark = pytest.mark.unit

BASE = "https://graph.facebook.com/v26.0"
MEDIA_ID = "1234567890"
INFO_URL = f"{BASE}/{MEDIA_ID}"
DOWNLOAD_URL = "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1"
FRESH_URL = "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=2"
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
CAP = 1000
VOICE = b"OggS" + bytes(range(200))
REF = MediaRef(
    channel=Channel.WHATSAPP, provider_media_id=MEDIA_ID, blob_id=None, mime_type="audio/ogg"
)


def info(url: str = DOWNLOAD_URL, data: bytes = VOICE, size: int | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "messaging_product": "whatsapp",
            "url": url,
            "mime_type": "audio/ogg; codecs=opus",
            "sha256": hashlib.sha256(data).hexdigest(),
            "file_size": len(data) if size is None else size,
            "id": MEDIA_ID,
        },
    )


@pytest.fixture
async def fetcher() -> AsyncIterator[WhatsAppMediaFetcher]:
    clock = FixedClock(NOW)
    retry = RetryPolicy(
        timing=RetryTiming(),
        clock=clock,
        sleeper=FakeSleeper(clock),
        rng=random.Random(7),  # noqa: S311  # deterministic jitter for tests, not cryptography
    )
    config = MediaFetchConfig(
        BASE, SecretStr("token-for-tests"), timeout_s=5, max_bytes=CAP, max_image_bytes=CAP
    )
    built = WhatsAppMediaFetcher(config=config, retry=retry, clock=clock, http=httpx.AsyncClient())
    yield built
    await built.aclose()


@respx.mock
async def test_the_two_step_download_sends_the_bearer_token_both_times(
    fetcher: WhatsAppMediaFetcher,
) -> None:
    info_route = respx.get(INFO_URL).mock(return_value=info())
    download_route = respx.get(DOWNLOAD_URL).mock(return_value=httpx.Response(200, content=VOICE))
    clip = await fetcher.fetch(REF)
    assert clip.data == VOICE
    assert clip.mime_type == "audio/ogg; codecs=opus"
    assert clip.duration_ms is None
    for route in (info_route, download_route):
        assert route.calls[0].request.headers["authorization"] == "Bearer token-for-tests"


@respx.mock
async def test_an_expired_url_is_asked_for_again_once(fetcher: WhatsAppMediaFetcher) -> None:
    info_route = respx.get(INFO_URL).mock(side_effect=[info(), info(FRESH_URL)])
    respx.get(DOWNLOAD_URL).mock(return_value=httpx.Response(404))
    respx.get(FRESH_URL).mock(return_value=httpx.Response(200, content=VOICE))
    assert (await fetcher.fetch(REF)).data == VOICE
    assert info_route.call_count == 2


@respx.mock
async def test_a_url_that_expires_twice_is_unavailable_and_retried_as_such(
    fetcher: WhatsAppMediaFetcher,
) -> None:
    respx.get(INFO_URL).mock(return_value=info())
    respx.get(DOWNLOAD_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(ProviderUnavailable, match="media url expired twice"):
        await fetcher.fetch(REF)


@respx.mock
async def test_a_file_over_the_cap_is_never_downloaded(fetcher: WhatsAppMediaFetcher) -> None:
    respx.get(INFO_URL).mock(return_value=info(size=CAP + 1))
    download_route = respx.get(DOWNLOAD_URL).mock(return_value=httpx.Response(200, content=VOICE))
    with pytest.raises(MediaTooLarge, match=f"voice note is {CAP + 1} bytes"):
        await fetcher.fetch(REF)
    assert download_route.call_count == 0


@respx.mock
async def test_a_file_exactly_at_the_cap_is_fine(fetcher: WhatsAppMediaFetcher) -> None:
    exactly = b"x" * CAP
    respx.get(INFO_URL).mock(return_value=info(data=exactly))
    respx.get(DOWNLOAD_URL).mock(return_value=httpx.Response(200, content=exactly))
    assert len((await fetcher.fetch(REF)).data) == CAP


@respx.mock
async def test_a_body_longer_than_declared_stops_at_the_cap(fetcher: WhatsAppMediaFetcher) -> None:
    respx.get(INFO_URL).mock(return_value=info(size=10))
    respx.get(DOWNLOAD_URL).mock(return_value=httpx.Response(200, content=b"x" * (CAP + 1)))
    with pytest.raises(MediaTooLarge, match="exceeded the size cap while downloading"):
        await fetcher.fetch(REF)


@respx.mock
async def test_a_checksum_mismatch_is_retried_once_then_invalid(
    fetcher: WhatsAppMediaFetcher,
) -> None:
    respx.get(INFO_URL).mock(return_value=info())
    download_route = respx.get(DOWNLOAD_URL).mock(
        return_value=httpx.Response(200, content=b"OggS tampered")
    )
    with pytest.raises(ProviderResponseInvalid, match="checksum mismatch"):
        await fetcher.fetch(REF)
    assert download_route.call_count == 2


@respx.mock
async def test_a_checksum_in_upper_case_still_matches(fetcher: WhatsAppMediaFetcher) -> None:
    upper = info().json() | {"sha256": hashlib.sha256(VOICE).hexdigest().upper()}
    respx.get(INFO_URL).mock(return_value=httpx.Response(200, json=upper))
    respx.get(DOWNLOAD_URL).mock(return_value=httpx.Response(200, content=VOICE))
    assert (await fetcher.fetch(REF)).data == VOICE


@pytest.mark.parametrize(
    ("response", "error", "calls"),
    [
        (httpx.Response(401, json={"error": {"code": 190}}), ProviderRejected, 1),
        (httpx.Response(404, json={"error": {"code": 100}}), ProviderRejected, 1),
        (httpx.Response(429), ProviderRateLimited, 3),
        (httpx.Response(500), ProviderUnavailable, 3),
    ],
    ids=["expired-token", "unknown-media", "rate-limited", "graph-down"],
)
@respx.mock
async def test_media_info_failures_are_typed_and_only_transient_ones_retried(
    fetcher: WhatsAppMediaFetcher, response: httpx.Response, error: type[Exception], calls: int
) -> None:
    route = respx.get(INFO_URL).mock(return_value=response)
    with pytest.raises(error):
        await fetcher.fetch(REF)
    assert route.call_count == calls


@pytest.mark.parametrize(
    "body",
    [
        {"url": DOWNLOAD_URL},
        {"url": DOWNLOAD_URL, "mime_type": "audio/ogg", "sha256": "x", "file_size": "big"},
    ],
    ids=["fields-missing", "size-not-a-number"],
)
@respx.mock
async def test_unexpected_media_info_is_invalid(
    fetcher: WhatsAppMediaFetcher, body: dict[str, str]
) -> None:
    respx.get(INFO_URL).mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(ProviderResponseInvalid, match="media info unexpected"):
        await fetcher.fetch(REF)


@pytest.mark.parametrize(
    ("failure", "error", "message"),
    [
        (httpx.ReadTimeout("slow"), ProviderTimeout, "media download timed out"),
        (httpx.ConnectError("refused"), ProviderUnavailable, "media download failed: ConnectError"),
    ],
)
@respx.mock
async def test_download_network_failures_are_typed(
    fetcher: WhatsAppMediaFetcher, failure: httpx.HTTPError, error: type[Exception], message: str
) -> None:
    respx.get(INFO_URL).mock(return_value=info())
    respx.get(DOWNLOAD_URL).mock(side_effect=failure)
    with pytest.raises(error, match=message):
        await fetcher.fetch(REF)


@respx.mock
async def test_a_download_5xx_is_retried_then_succeeds(fetcher: WhatsAppMediaFetcher) -> None:
    respx.get(INFO_URL).mock(return_value=info())
    respx.get(DOWNLOAD_URL).mock(
        side_effect=[httpx.Response(502), httpx.Response(200, content=VOICE)]
    )
    assert (await fetcher.fetch(REF)).data == VOICE


async def test_a_ref_without_a_whatsapp_media_id_is_refused(fetcher: WhatsAppMediaFetcher) -> None:
    stored = MediaRef(
        channel=Channel.WEB,
        provider_media_id=None,
        blob_id=uuid4(),
        mime_type="audio/webm",
    )
    with pytest.raises(ValueError, match="needs a WhatsApp media id"):
        await fetcher.fetch(stored)


# --- photos (s10b §4.14) --------------------------------------------------------------------------

IMAGE_CAP = 2000  # photos have their own cap, separate from voice notes'
JPEG = b"\xff\xd8\xff\xe0" + bytes(range(200))
PHOTO_REF = REF.model_copy(update={"mime_type": "image/jpeg"})


def photo_info(mime_type: str, data: bytes = JPEG, size: int | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "messaging_product": "whatsapp",
            "url": DOWNLOAD_URL,
            "mime_type": mime_type,
            "sha256": hashlib.sha256(data).hexdigest(),
            "file_size": len(data) if size is None else size,
            "id": MEDIA_ID,
        },
    )


@pytest.fixture
async def photo_fetcher() -> AsyncIterator[WhatsAppMediaFetcher]:
    clock = FixedClock(NOW)
    retry = RetryPolicy(
        timing=RetryTiming(),
        clock=clock,
        sleeper=FakeSleeper(clock),
        rng=random.Random(7),  # noqa: S311  # deterministic jitter for tests, not cryptography
    )
    config = MediaFetchConfig(
        BASE, SecretStr("token-for-tests"), timeout_s=5, max_bytes=CAP, max_image_bytes=IMAGE_CAP
    )
    built = WhatsAppMediaFetcher(config=config, retry=retry, clock=clock, http=httpx.AsyncClient())
    yield built
    await built.aclose()


@pytest.mark.parametrize("mime_type", ["image/jpeg", "image/png", "IMAGE/WEBP", "image/jpeg; q=1"])
@respx.mock
async def test_a_photo_is_downloaded_the_same_way_and_typed(
    photo_fetcher: WhatsAppMediaFetcher, mime_type: str
) -> None:
    respx.get(INFO_URL).mock(return_value=photo_info(mime_type))
    respx.get(DOWNLOAD_URL).mock(return_value=httpx.Response(200, content=JPEG))
    image = await photo_fetcher.fetch_image(PHOTO_REF)
    assert image.data == JPEG
    assert image.mime_type == mime_type.split(";", maxsplit=1)[0].strip().lower()


@pytest.mark.parametrize("mime_type", ["image/gif", "video/mp4", "application/pdf", ""])
@respx.mock
async def test_anything_but_a_jpeg_png_or_webp_photo_is_unsupported(
    photo_fetcher: WhatsAppMediaFetcher, mime_type: str
) -> None:
    respx.get(INFO_URL).mock(return_value=photo_info(mime_type))
    respx.get(DOWNLOAD_URL).mock(return_value=httpx.Response(200, content=JPEG))
    with pytest.raises(MediaUnsupported, match="is not accepted"):
        await photo_fetcher.fetch_image(PHOTO_REF)


@respx.mock
async def test_the_photo_cap_is_exact_and_separate_from_the_voice_cap(
    photo_fetcher: WhatsAppMediaFetcher,
) -> None:
    exactly = b"\xff\xd8\xff" + b"x" * (IMAGE_CAP - 3)  # over the voice cap, at the photo cap
    respx.get(INFO_URL).mock(return_value=photo_info("image/jpeg", data=exactly))
    respx.get(DOWNLOAD_URL).mock(return_value=httpx.Response(200, content=exactly))
    assert len((await photo_fetcher.fetch_image(PHOTO_REF)).data) == IMAGE_CAP


@respx.mock
async def test_a_photo_over_its_cap_is_never_downloaded(
    photo_fetcher: WhatsAppMediaFetcher,
) -> None:
    respx.get(INFO_URL).mock(return_value=photo_info("image/jpeg", size=IMAGE_CAP + 1))
    download_route = respx.get(DOWNLOAD_URL).mock(return_value=httpx.Response(200, content=JPEG))
    with pytest.raises(MediaTooLarge, match=f"photo is {IMAGE_CAP + 1} bytes"):
        await photo_fetcher.fetch_image(PHOTO_REF)
    assert download_route.call_count == 0


@respx.mock
async def test_a_photo_with_a_wrong_checksum_is_invalid(
    photo_fetcher: WhatsAppMediaFetcher,
) -> None:
    respx.get(INFO_URL).mock(return_value=photo_info("image/jpeg"))
    respx.get(DOWNLOAD_URL).mock(return_value=httpx.Response(200, content=JPEG + b"tampered"))
    with pytest.raises(ProviderResponseInvalid, match="photo checksum mismatch"):
        await photo_fetcher.fetch_image(PHOTO_REF)
