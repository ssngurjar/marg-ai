"""MuseImageGenerator against a scripted endpoint (s10b §4.13, spike F)."""

import base64
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import httpx2
import pytest
from pydantic import SecretStr

from app.audio.ffmpeg_runner import FfmpegRunner
from app.core.errors import ConfigError, ProviderRejected, ProviderResponseInvalid
from app.providers.http import RetryPolicy, RetryTiming
from app.providers.image.image_compressor import ImageCompressor
from app.providers.image.muse_image_generator import ImageModelConfig, MuseImageGenerator
from tests.fakes.clock import FixedClock
from tests.fakes.image import TINY_PNG
from tests.fakes.openai_endpoint import BASE_URL, ScriptedEndpoint, ScriptedReply
from tests.fakes.sleeper import FakeSleeper

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
COMPRESSOR = ImageCompressor(FfmpegRunner(timeout_s=10))
PROMPT = "A warm Indian folk-art illustration... Subject: stones stacked into a tower"


def image_reply(encoded: str | None) -> httpx2.Response:
    data = [] if encoded is None else [{"b64_json": encoded}]
    return httpx2.Response(200, json={"created": 1, "data": data})


def config(model: str = "muse-image-1.0") -> ImageModelConfig:
    return ImageModelConfig(
        base_url=BASE_URL,
        api_key=SecretStr("key-for-tests"),
        model=model,
        reasoning_strength="low",
        timeout_s=30,
    )


async def generator_for(*replies: ScriptedReply) -> tuple[MuseImageGenerator, ScriptedEndpoint]:
    clock = FixedClock(NOW)
    retry = RetryPolicy(
        timing=RetryTiming(),
        clock=clock,
        sleeper=FakeSleeper(clock),
        rng=random.Random(7),  # noqa: S311  # deterministic jitter for tests, not cryptography
    )
    endpoint = ScriptedEndpoint(replies)
    return MuseImageGenerator(
        config=config(), retry=retry, clock=clock, compressor=COMPRESSOR, client=endpoint.client()
    ), endpoint


@pytest.fixture
async def png_endpoint() -> AsyncIterator[tuple[MuseImageGenerator, ScriptedEndpoint]]:
    generator, endpoint = await generator_for(
        image_reply(base64.b64encode(TINY_PNG).decode("ascii"))
    )
    yield generator, endpoint
    await generator.aclose()


async def test_the_request_is_one_png_at_low_strength_and_the_cost_is_recorded(
    png_endpoint: tuple[MuseImageGenerator, ScriptedEndpoint],
) -> None:
    generator, endpoint = png_endpoint
    image, usage = await generator.generate(PROMPT)
    assert image.mime_type == "image/jpeg"  # the 5 MB PNG is sent as a small JPEG
    assert image.data.startswith(b"\xff\xd8\xff")
    body = endpoint.bodies[0]
    assert body["model"] == "muse-image-1.0"
    assert body["prompt"] == PROMPT
    assert body["size"] == "1024x1024"
    assert body["response_format"] == "b64_json"
    assert body["reasoning_strength"] == "low"
    assert (usage.model, usage.cost_usd) == ("muse-image-1.0", Decimal("0.01"))


@pytest.mark.parametrize(
    ("encoded", "message"),
    [
        (None, "returned no image"),
        ("", "returned no image"),
        ("not base64!!", "undecodable"),
        (base64.b64encode(b"GIF89a").decode("ascii"), "returned no PNG"),
    ],
    ids=["no-data", "empty", "garbage", "not-png"],
)
async def test_a_bad_answer_is_invalid(encoded: str | None, message: str) -> None:
    generator, _ = await generator_for(image_reply(encoded))
    with pytest.raises(ProviderResponseInvalid, match=message):
        await generator.generate(PROMPT)


async def test_a_refused_prompt_is_rejected_without_retry() -> None:
    generator, endpoint = await generator_for(
        httpx2.Response(400, json={"error": {"message": "content policy"}})
    )
    with pytest.raises(ProviderRejected):
        await generator.generate(PROMPT)
    assert endpoint.call_count == 1


def test_a_model_without_a_price_is_refused_at_startup() -> None:
    clock = FixedClock(NOW)
    retry = RetryPolicy(
        timing=RetryTiming(),
        clock=clock,
        sleeper=FakeSleeper(clock),
        rng=random.Random(7),  # noqa: S311  # deterministic jitter for tests, not cryptography
    )
    with pytest.raises(ConfigError, match="no price listed for image model muse-image-9"):
        MuseImageGenerator(
            config=config("muse-image-9"), retry=retry, clock=clock, compressor=COMPRESSOR
        )
