"""SidecarEmbedder: the voice server's /embed (s11 §4.4)."""

import json
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.core.errors import (
    ProviderRejected,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.domain.enums import EmbedPurpose
from app.providers.embeddings.sidecar_embedder import EmbedderConfig, SidecarEmbedder
from app.providers.http import RetryPolicy, RetryTiming
from tests.fakes.clock import FixedClock
from tests.fakes.sleeper import FakeSleeper

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)
BASE = "http://voice.test"
URL = f"{BASE}/embed"
MODEL = "intfloat/multilingual-e5-small"


def reply(count: int, *, model: str = MODEL, length: int = 384) -> httpx.Response:
    return httpx.Response(
        200, json={"model": model, "dimensions": length, "vectors": [[0.1] * length] * count}
    )


def echo(request: httpx.Request) -> httpx.Response:
    texts = json.loads(request.content)["texts"]
    return reply(len(texts))


@pytest.fixture
async def embedder() -> AsyncIterator[SidecarEmbedder]:
    clock = FixedClock(NOW)
    retry = RetryPolicy(
        timing=RetryTiming(),
        clock=clock,
        sleeper=FakeSleeper(clock),
        rng=random.Random(7),  # noqa: S311  # deterministic jitter for tests, not cryptography
    )
    built = SidecarEmbedder(
        config=EmbedderConfig(BASE, SecretStr("test-sidecar-token"), MODEL, timeout_s=5),
        retry=retry,
        clock=clock,
        http=httpx.AsyncClient(),
    )
    yield built
    await built.aclose()


@pytest.mark.parametrize(
    ("purpose", "prefix"), [(EmbedPurpose.QUERY, "query: "), (EmbedPurpose.PASSAGE, "passage: ")]
)
@respx.mock
async def test_the_e5_prefix_is_added_and_the_token_sent(
    embedder: SidecarEmbedder, purpose: EmbedPurpose, prefix: str
) -> None:
    route = respx.post(URL).mock(side_effect=echo)
    vectors = await embedder.embed(["क्लास 8 स्कॉलरशिप"], purpose)
    assert len(vectors) == 1
    assert len(vectors[0]) == 384
    request = route.calls[0].request
    assert json.loads(request.content) == {"texts": [f"{prefix}क्लास 8 स्कॉलरशिप"]}
    assert request.headers["authorization"] == "Bearer test-sidecar-token"


@respx.mock
async def test_texts_go_in_batches_of_32_and_keep_their_order(embedder: SidecarEmbedder) -> None:
    route = respx.post(URL).mock(side_effect=echo)
    vectors = await embedder.embed([f"text {n}" for n in range(70)], EmbedPurpose.PASSAGE)
    assert len(vectors) == 70
    sizes = [len(json.loads(call.request.content)["texts"]) for call in route.calls]
    assert sizes == [32, 32, 6]


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (reply(1, model="sentence-transformers/all-MiniLM-L6-v2"), "embed server runs"),
        (reply(1, length=768), "aren't 384 long"),
        (reply(2), "2 vectors for 1"),
        (httpx.Response(200, json={"vectors": "nope"}), "isn't the /embed shape"),
        (httpx.Response(200, content=b"<html>"), "isn't the /embed shape"),
    ],
    ids=["wrong_model", "wrong_length", "wrong_count", "wrong_shape", "not_json"],
)
@respx.mock
async def test_a_reply_that_doesnt_fit_the_model_is_invalid(
    embedder: SidecarEmbedder, answer: httpx.Response, message: str
) -> None:
    respx.post(URL).mock(return_value=answer)
    with pytest.raises(ProviderResponseInvalid, match=message):
        await embedder.embed(["text"], EmbedPurpose.QUERY)


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        (httpx.Response(401), ProviderRejected),
        (httpx.Response(422), ProviderRejected),
        (httpx.Response(503), ProviderUnavailable),
        (httpx.ReadTimeout("slow"), ProviderTimeout),
        (httpx.ConnectError("refused"), ProviderUnavailable),
    ],
    ids=["unauthorised", "invalid_request", "5xx", "timeout", "down"],
)
@respx.mock
async def test_failures_are_typed(
    embedder: SidecarEmbedder, answer: httpx.Response | Exception, error: type[Exception]
) -> None:
    respx.post(URL).mock(side_effect=[answer, answer, answer, answer])
    with pytest.raises(error):
        await embedder.embed(["text"], EmbedPurpose.QUERY)


@respx.mock
async def test_a_5xx_is_retried(embedder: SidecarEmbedder) -> None:
    route = respx.post(URL).mock(side_effect=[httpx.Response(503), reply(1)])
    assert len(await embedder.embed(["text"], EmbedPurpose.QUERY)) == 1
    assert route.call_count == 2


async def test_nothing_to_embed_makes_no_call(embedder: SidecarEmbedder) -> None:
    assert await embedder.embed([], EmbedPurpose.PASSAGE) == []
