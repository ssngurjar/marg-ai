"""SamImageSegmenter against a scripted endpoint (s10b §4.14, spike F)."""

import base64
import random
from datetime import UTC, datetime
from decimal import Decimal

import httpx2
import pytest
from pydantic import SecretStr

from app.core.errors import (
    ConfigError,
    ProviderRateLimited,
    ProviderRejected,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.domain.models.message import ImageClip
from app.domain.models.photo import ObjectCount
from app.providers.http import RetryPolicy, RetryTiming
from app.providers.image.sam_image_segmenter import SamImageSegmenter, SegmentModelConfig
from tests.fakes.clock import FixedClock
from tests.fakes.openai_endpoint import BASE_URL, ScriptedEndpoint, ScriptedReply
from tests.fakes.sleeper import FakeSleeper
from tests.fakes.voice import PHOTO_JPEG

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)
PHOTO = ImageClip(data=PHOTO_JPEG, mime_type="image/jpeg")
BOX = "<|box;x=10;y=20;w=30;h=40;c=0.95|>"


def answer(text: str) -> httpx2.Response:
    """A Responses API answer whose output_text is `text` (spike F: one box token per object)."""
    return httpx2.Response(
        200,
        json={
            "id": "resp_1",
            "object": "response",
            "created_at": 1,
            "model": "sam-3.1",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "id": "msg_1",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": text, "annotations": []}],
                }
            ],
        },
    )


def retry_policy(clock: FixedClock) -> RetryPolicy:
    return RetryPolicy(
        timing=RetryTiming(),
        clock=clock,
        sleeper=FakeSleeper(clock),
        rng=random.Random(7),  # noqa: S311  # deterministic jitter for tests, not cryptography
    )


def config(model: str = "sam-3.1") -> SegmentModelConfig:
    return SegmentModelConfig(
        base_url=BASE_URL, api_key=SecretStr("key-for-tests"), model=model, timeout_s=6
    )


def segmenter_for(*replies: ScriptedReply) -> tuple[SamImageSegmenter, ScriptedEndpoint]:
    clock = FixedClock(NOW)
    endpoint = ScriptedEndpoint(replies)
    segmenter = SamImageSegmenter(
        config=config(), retry=retry_policy(clock), clock=clock, client=endpoint.client()
    )
    return segmenter, endpoint


async def test_each_phrase_is_one_call_with_the_photo_inline_and_the_boxes_are_counted() -> None:
    segmenter, endpoint = segmenter_for(answer(BOX * 7))
    counts, usage = await segmenter.count(PHOTO, ["leaf"])
    assert counts == [ObjectCount(phrase="leaf", count=7)]
    body = endpoint.bodies[0]
    assert body["model"] == "sam-3.1"
    assert body["metadata"] == {"include_confidence": "true", "mask_encoding": "one_bit"}
    encoded = base64.b64encode(PHOTO_JPEG).decode("ascii")
    assert body["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "leaf"},
                {
                    "type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{encoded}",
                    "detail": "auto",
                },
            ],
        }
    ]
    assert (usage.model, usage.cost_usd) == ("sam-3.1", Decimal("0.0025"))


async def test_several_phrases_are_counted_in_order_and_each_call_is_billed() -> None:
    segmenter, endpoint = segmenter_for(answer(BOX))
    counts, usage = await segmenter.count(PHOTO, ["person", "face"])
    assert [count.phrase for count in counts] == ["person", "face"]
    assert endpoint.call_count == 2
    assert usage.cost_usd == Decimal("0.0050")


@pytest.mark.parametrize("text", ["", "No objects found.", "   "])
async def test_an_answer_without_boxes_counts_zero(text: str) -> None:
    segmenter, _ = segmenter_for(answer(text))
    counts, _ = await segmenter.count(PHOTO, ["person"])
    assert counts == [ObjectCount(phrase="person", count=0)]


@pytest.mark.parametrize(
    "text",
    ["<|box;x=1;c=0.9", "<|box;c=high|>", "<|box;c=1.7|>"],
    ids=["unclosed", "word_confidence", "confidence_over_one"],
)
async def test_a_malformed_answer_is_invalid_never_a_guess(text: str) -> None:
    segmenter, _ = segmenter_for(answer(text))
    with pytest.raises(ProviderResponseInvalid, match="sam returned a malformed"):
        await segmenter.count(PHOTO, ["leaf"])


async def test_a_server_error_is_retried_then_counts() -> None:
    segmenter, endpoint = segmenter_for(httpx2.Response(503), answer(BOX * 2))
    counts, _ = await segmenter.count(PHOTO, ["stone"])
    assert counts == [ObjectCount(phrase="stone", count=2)]
    assert endpoint.call_count == 2


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (httpx2.Response(400, json={"error": {"message": "bad image"}}), ProviderRejected),
        (httpx2.Response(429, headers={"retry-after": "1"}), ProviderRateLimited),
        (httpx2.Response(429), ProviderRateLimited),
        (httpx2.Response(500), ProviderUnavailable),
        (httpx2.ReadTimeout("slow"), ProviderTimeout),
    ],
    ids=["rejected", "429_retry_after", "429_bare", "5xx", "timeout"],
)
async def test_a_failing_provider_raises_a_typed_error(
    reply: ScriptedReply, error: type[Exception]
) -> None:
    segmenter, _ = segmenter_for(reply)
    with pytest.raises(error):
        await segmenter.count(PHOTO, ["leaf"])


async def test_counting_nothing_is_a_programming_error() -> None:
    segmenter, endpoint = segmenter_for(answer(BOX))
    with pytest.raises(ValueError, match="at least one phrase"):
        await segmenter.count(PHOTO, [])
    assert endpoint.call_count == 0


def test_a_model_without_a_price_is_refused_at_startup() -> None:
    clock = FixedClock(NOW)
    with pytest.raises(ConfigError, match="no price listed for segmentation model sam-9"):
        SamImageSegmenter(config=config("sam-9"), retry=retry_policy(clock), clock=clock)
