"""LlamaGuardClassifier against a scripted OpenAI-compatible host (s07 §4.3)."""

import base64
import random
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

import httpx2
import pytest
from pydantic import SecretStr

from app.core.errors import (
    ProviderRateLimited,
    ProviderRejected,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.domain.enums import SafetyCategory, SafetyDecision
from app.domain.models.message import ImageClip
from app.providers.http import RetryPolicy, RetryTiming
from app.providers.ports import SafetyRequest
from app.providers.safety.llama_guard_classifier import LlamaGuardClassifier, SafetyHostConfig
from tests.fakes.clock import FixedClock
from tests.fakes.openai_endpoint import ScriptedEndpoint, ScriptedReply, api_error, chat_completion
from tests.fakes.sleeper import FakeSleeper

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
GUARD = "meta-llama/Llama-Guard-4-12B"
USER_CHECK = SafetyRequest(speaker="user", text="Beta ko rang sikhana hai", prior_user_text=None)
REPLY_CHECK = SafetyRequest(
    speaker="assistant", text="Roz rang ka khel kheliye.", prior_user_text="Rang kaise sikhayein?"
)


@dataclass(frozen=True, slots=True)
class Harness:
    classifier: LlamaGuardClassifier
    endpoint: ScriptedEndpoint
    sleeper: FakeSleeper


class HarnessFactory(Protocol):
    def __call__(self, *replies: ScriptedReply) -> Harness: ...


@pytest.fixture
async def harness_for() -> AsyncIterator[HarnessFactory]:
    built: list[LlamaGuardClassifier] = []

    def build(*replies: ScriptedReply) -> Harness:
        clock = FixedClock(NOW)
        sleeper = FakeSleeper(clock)
        retry = RetryPolicy(
            timing=RetryTiming(),
            clock=clock,
            sleeper=sleeper,
            rng=random.Random(7),  # noqa: S311  # deterministic jitter for tests, not cryptography
        )
        endpoint = ScriptedEndpoint(replies)
        classifier = LlamaGuardClassifier(
            config=SafetyHostConfig(
                base_url="https://unused.test/v1",
                api_key=SecretStr("unused"),
                model=GUARD,
                timeout_s=3,
            ),
            retry=retry,
            clock=clock,
            client=endpoint.client(),
        )
        built.append(classifier)
        return Harness(classifier, endpoint, sleeper)

    yield build
    for classifier in built:
        await classifier.aclose()


def guard_answer(text: str | None) -> httpx2.Response:
    return chat_completion(text, prompt_tokens=200, completion_tokens=3)


async def test_safe_is_allowed_and_priced(harness_for: HarnessFactory) -> None:
    harness = harness_for(guard_answer("safe"))
    verdict, usage = await harness.classifier.classify(USER_CHECK)
    assert verdict.decision is SafetyDecision.ALLOW
    assert verdict.categories == []
    assert verdict.source == "llama_guard"
    assert usage.model == GUARD
    assert usage.cost_usd == Decimal("0.000037")


async def test_unsafe_is_flagged_with_its_categories(harness_for: HarnessFactory) -> None:
    harness = harness_for(guard_answer("unsafe\nS11"))
    verdict, _ = await harness.classifier.classify(USER_CHECK)
    assert verdict.decision is SafetyDecision.BLOCK
    assert verdict.categories == [SafetyCategory.SELF_HARM]


async def test_a_user_check_sends_only_the_users_turn(harness_for: HarnessFactory) -> None:
    harness = harness_for(guard_answer("safe"))
    await harness.classifier.classify(USER_CHECK)
    body = harness.endpoint.bodies[0]
    assert body["messages"] == [{"role": "user", "content": "Beta ko rang sikhana hai"}]
    assert body["model"] == GUARD
    assert body["temperature"] == 0
    assert body["max_tokens"] == 20


async def test_a_reply_check_sends_the_question_then_our_reply(
    harness_for: HarnessFactory,
) -> None:
    harness = harness_for(guard_answer("safe"))
    await harness.classifier.classify(REPLY_CHECK)
    assert harness.endpoint.bodies[0]["messages"] == [
        {"role": "user", "content": "Rang kaise sikhayein?"},
        {"role": "assistant", "content": "Roz rang ka khel kheliye."},
    ]


async def test_a_reply_check_without_the_question_is_a_programming_error(
    harness_for: HarnessFactory,
) -> None:
    harness = harness_for(guard_answer("safe"))
    orphan = SafetyRequest(speaker="assistant", text="reply", prior_user_text=None)
    with pytest.raises(ValueError, match="a reply check needs the user's message"):
        await harness.classifier.classify(orphan)
    assert harness.endpoint.call_count == 0


async def test_an_image_goes_with_its_caption_in_one_user_turn(
    harness_for: HarnessFactory,
) -> None:
    """Spike B: the host takes an image only together with a text part (alone it returns 500)."""
    harness = harness_for(guard_answer("safe"))
    card = SafetyRequest(
        speaker="assistant",
        text="Munni ne parchhai ka raaz khoja!",
        prior_user_text=None,
        image=ImageClip(data=b"\x89PNG\r\n\x1a\nfake", mime_type="image/png"),
    )
    verdict, _ = await harness.classifier.classify(card)
    assert verdict.decision is SafetyDecision.ALLOW
    encoded = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode("ascii")
    assert harness.endpoint.bodies[0]["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Munni ne parchhai ka raaz khoja!"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ],
        }
    ]


@pytest.mark.parametrize("answer", ["probably safe", "I cannot help", "unsafe", "unsafe\nS99"])
async def test_an_unreadable_answer_is_retried_once_then_invalid(
    harness_for: HarnessFactory, answer: str
) -> None:
    harness = harness_for(guard_answer(answer))
    with pytest.raises(ProviderResponseInvalid):
        await harness.classifier.classify(USER_CHECK)


@pytest.mark.parametrize("content", [None, ""], ids=["null", "empty"])
async def test_no_answer_is_invalid(harness_for: HarnessFactory, content: str | None) -> None:
    harness = harness_for(guard_answer(content))
    with pytest.raises(ProviderResponseInvalid, match="llama guard returned no answer"):
        await harness.classifier.classify(USER_CHECK)


async def test_a_429_honours_retry_after(harness_for: HarnessFactory) -> None:
    harness = harness_for(api_error(429, {"retry-after": "1"}), guard_answer("safe"))
    verdict, _ = await harness.classifier.classify(USER_CHECK)
    assert verdict.decision is SafetyDecision.ALLOW
    assert harness.sleeper.waits == [1.0]


async def test_a_429_past_the_timeout_is_not_waited_for(harness_for: HarnessFactory) -> None:
    harness = harness_for(api_error(429, {"retry-after": "30"}))
    with pytest.raises(ProviderRateLimited, match="llama guard: RateLimitError rate limited"):
        await harness.classifier.classify(USER_CHECK)
    assert harness.endpoint.call_count == 1
    assert harness.sleeper.waits == []


async def test_a_server_error_is_unavailable(harness_for: HarnessFactory) -> None:
    harness = harness_for(api_error(503))
    with pytest.raises(ProviderUnavailable, match="llama guard: InternalServerError unavailable"):
        await harness.classifier.classify(USER_CHECK)


async def test_a_bad_key_is_rejected_without_retry(harness_for: HarnessFactory) -> None:
    harness = harness_for(api_error(401))
    with pytest.raises(ProviderRejected, match="rejected: HTTP 401"):
        await harness.classifier.classify(USER_CHECK)
    assert harness.endpoint.call_count == 1


async def test_a_timeout_is_a_provider_timeout(harness_for: HarnessFactory) -> None:
    harness = harness_for(httpx2.ReadTimeout("slow"))
    with pytest.raises(ProviderTimeout, match="llama guard: APITimeoutError timed out"):
        await harness.classifier.classify(USER_CHECK)
