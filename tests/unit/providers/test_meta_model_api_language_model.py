"""MetaModelApiLanguageModel against a scripted Chat Completions endpoint (s05 §4.1, ADR 0007).

A real AsyncOpenAI client talks to the endpoint, so the SDK's own parsing and error types are
exercised.
"""

import base64
import json
import random
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

import httpx2
import pytest
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.core.errors import (
    ProviderRateLimited,
    ProviderRejected,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.core.types import JsonValue
from app.domain.models.message import ImageClip
from app.providers.http import RetryPolicy, RetryTiming
from app.providers.llm.meta_model_api_language_model import (
    MetaModelApiLanguageModel,
    ModelApiConfig,
)
from app.providers.ports import GenerationRequest, RenderedPrompt
from tests.fakes.clock import FixedClock
from tests.fakes.openai_endpoint import ScriptedEndpoint, ScriptedReply, api_error, chat_completion
from tests.fakes.sleeper import FakeSleeper

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
USER_TEXT = "Mera beta rangon mein dilchaspi nahi leta"
VALID = json.dumps({"tip": "Rang ke naam se khilona dhoondhiye"})


class Tip(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tip: str = Field(min_length=1, max_length=40)


@dataclass(frozen=True, slots=True)
class Harness:
    model: MetaModelApiLanguageModel
    sleeper: FakeSleeper
    endpoint: ScriptedEndpoint

    def message(self, call: int, index: int) -> JsonValue:
        messages = self.endpoint.bodies[call]["messages"]
        assert isinstance(messages, list)
        return messages[index]


class HarnessFactory(Protocol):
    def __call__(self, *replies: ScriptedReply) -> Harness: ...


@pytest.fixture
async def harness_for() -> AsyncIterator[HarnessFactory]:
    built: list[MetaModelApiLanguageModel] = []

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
        model = MetaModelApiLanguageModel(
            config=ModelApiConfig(
                base_url="https://unused.test/v1", api_key=SecretStr("unused"), timeout_s=12
            ),
            retry=retry,
            clock=clock,
            client=endpoint.client(),
        )
        built.append(model)
        return Harness(model, sleeper, endpoint)

    yield build
    for model in built:
        await model.aclose()


def request(semantic_problems: list[str] | None = None) -> GenerationRequest[Tip]:
    def check(tip: Tip) -> list[str]:
        return list(semantic_problems or [])

    return GenerationRequest[Tip](
        prompt=RenderedPrompt(
            prompt_id="tip", prompt_version="1.0.0", system="Give one tip.", user=USER_TEXT
        ),
        output_type=Tip,
        model="muse-spark-1.3",
        reasoning_effort="minimal",
        max_output_tokens=300,
        semantic_check=check if semantic_problems else None,
    )


async def test_a_valid_reply_is_parsed_and_priced(harness_for: HarnessFactory) -> None:
    harness = harness_for(chat_completion(VALID))
    result = await harness.model.generate(request())
    assert result.output == Tip(tip="Rang ke naam se khilona dhoondhiye")
    assert result.usage.input_tokens == 1000
    assert result.usage.output_tokens == 100
    assert result.usage.cost_usd == Decimal("0.001675")
    assert harness.endpoint.call_count == 1


async def test_the_request_asks_for_strict_json_at_the_configured_effort(
    harness_for: HarnessFactory,
) -> None:
    harness = harness_for(chat_completion(VALID))
    await harness.model.generate(request())
    body = harness.endpoint.bodies[0]
    assert body["model"] == "muse-spark-1.3"
    assert body["reasoning_effort"] == "minimal"
    assert body["max_tokens"] == 300
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "tip", "schema": Tip.model_json_schema(), "strict": True},
    }
    assert body["messages"] == [
        {"role": "system", "content": "Give one tip."},
        {"role": "user", "content": USER_TEXT},
    ]


@pytest.mark.parametrize(
    "first",
    [
        "Sure! Here is a tip: play colour games.",  # prose where JSON was asked
        json.dumps({"tip": ""}),  # validates as JSON, empty field
        json.dumps({"tip": "x" * 41}),  # too long
        json.dumps({"advice": "play"}),  # wrong field
    ],
    ids=["prose", "empty-field", "too-long", "wrong-field"],
)
async def test_an_invalid_reply_gets_one_repair_turn(
    harness_for: HarnessFactory, first: str
) -> None:
    harness = harness_for(chat_completion(first), chat_completion(VALID))
    result = await harness.model.generate(request())
    assert result.output.tip == "Rang ke naam se khilona dhoondhiye"
    assert harness.endpoint.call_count == 2
    assert harness.message(1, 2) == {"role": "assistant", "content": first}
    repair = harness.message(1, 3)
    assert isinstance(repair, dict)
    assert str(repair["content"]).startswith("Your previous reply did not pass validation. ")
    assert result.usage.input_tokens == 2000  # both attempts are billed


async def test_repair_errors_never_echo_the_invalid_value(harness_for: HarnessFactory) -> None:
    invalid_value = "x" * 41
    harness = harness_for(
        chat_completion(json.dumps({"tip": invalid_value})), chat_completion(VALID)
    )
    await harness.model.generate(request())
    repair = harness.message(1, 3)
    assert isinstance(repair, dict)
    assert invalid_value not in str(repair["content"])


async def test_a_semantic_problem_is_sent_back_for_repair(harness_for: HarnessFactory) -> None:
    harness = harness_for(chat_completion(VALID))
    with pytest.raises(ProviderResponseInvalid, match="tip: reply failed validation after one"):
        await harness.model.generate(request(["tip: expected Devanagari script"]))
    assert harness.endpoint.call_count == 2
    repair = harness.message(1, 3)
    assert isinstance(repair, dict)
    assert "tip: expected Devanagari script" in str(repair["content"])


async def test_a_second_invalid_reply_is_a_permanent_failure(harness_for: HarnessFactory) -> None:
    harness = harness_for(chat_completion("not json"))
    with pytest.raises(ProviderResponseInvalid) as raised:
        await harness.model.generate(request())
    assert raised.value.retryable is False


async def test_a_reply_cut_at_max_tokens_is_not_retried(harness_for: HarnessFactory) -> None:
    harness = harness_for(chat_completion('{"tip": "Rang', finish_reason="length"))
    with pytest.raises(ProviderResponseInvalid, match="output truncated at max_tokens=300"):
        await harness.model.generate(request())
    assert harness.endpoint.call_count == 1


@pytest.mark.parametrize("content", [None, ""], ids=["null", "empty"])
async def test_an_empty_reply_is_invalid(harness_for: HarnessFactory, content: str | None) -> None:
    harness = harness_for(chat_completion(content))
    with pytest.raises(ProviderResponseInvalid, match="tip: empty content"):
        await harness.model.generate(request())


async def test_a_429_with_retry_after_waits_that_long(harness_for: HarnessFactory) -> None:
    harness = harness_for(api_error(429, {"retry-after": "2"}), chat_completion(VALID))
    await harness.model.generate(request())
    assert harness.endpoint.call_count == 2
    assert harness.sleeper.waits == [2.0]


async def test_a_429_without_retry_after_backs_off_then_gives_up(
    harness_for: HarnessFactory,
) -> None:
    harness = harness_for(api_error(429))
    with pytest.raises(ProviderRateLimited, match="tip: RateLimitError rate limited") as raised:
        await harness.model.generate(request())
    assert raised.value.retry_after is None
    assert harness.endpoint.call_count == 3
    assert all(0 <= wait <= 4.0 for wait in harness.sleeper.waits)


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_server_errors_are_retried_then_unavailable(
    harness_for: HarnessFactory, status: int
) -> None:
    harness = harness_for(api_error(status))
    with pytest.raises(ProviderUnavailable, match="unavailable"):
        await harness.model.generate(request())
    assert harness.endpoint.call_count == 3


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_client_errors_are_rejected_without_retry(
    harness_for: HarnessFactory, status: int
) -> None:
    harness = harness_for(api_error(status))
    with pytest.raises(ProviderRejected, match=f"rejected: HTTP {status}"):
        await harness.model.generate(request())
    assert harness.endpoint.call_count == 1


async def test_a_timeout_is_retried_then_raised(harness_for: HarnessFactory) -> None:
    harness = harness_for(httpx2.ReadTimeout("slow"))
    with pytest.raises(ProviderTimeout, match="tip: APITimeoutError timed out"):
        await harness.model.generate(request())
    assert harness.endpoint.call_count == 3


async def test_a_connection_failure_is_unavailable(harness_for: HarnessFactory) -> None:
    harness = harness_for(httpx2.ConnectError("refused"))
    with pytest.raises(ProviderUnavailable, match="APIConnectionError unavailable"):
        await harness.model.generate(request())


async def test_a_request_with_an_image_sends_it_beside_the_text(
    harness_for: HarnessFactory,
) -> None:
    """The image backup check (owner, 2026-10-31): Muse Spark sees the card or photo itself."""
    harness = harness_for(chat_completion(VALID))
    picture = ImageClip(data=b"\xff\xd8\xff\xe0card", mime_type="image/jpeg")
    await harness.model.generate(request().model_copy(update={"image": picture}))
    user = harness.message(0, 1)
    assert isinstance(user, dict)
    assert user["content"] == [
        {"type": "text", "text": USER_TEXT},
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{base64.b64encode(picture.data).decode()}"
            },
        },
    ]


async def test_a_request_without_an_image_sends_plain_text(harness_for: HarnessFactory) -> None:
    harness = harness_for(chat_completion(VALID))
    await harness.model.generate(request())
    assert harness.message(0, 1) == {"role": "user", "content": USER_TEXT}
