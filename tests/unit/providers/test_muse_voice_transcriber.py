"""MuseVoiceTranscriber against a faked endpoint (s06 §4.5, §9)."""

import json
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.core.errors import (
    ConfigError,
    ProviderRateLimited,
    ProviderRejected,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.domain.enums import Language
from app.domain.models.message import AudioClip
from app.providers.http import RetryPolicy, RetryTiming
from app.providers.ports import TranscriptionHints
from app.providers.speech.muse_voice_transcriber import MuseVoiceTranscriber, TranscriberConfig
from tests.fakes.clock import FixedClock
from tests.fakes.sleeper import FakeSleeper

pytestmark = pytest.mark.unit

BASE = "https://api.meta.ai/v1"
URL = f"{BASE}/asr/transcribe"
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
WAV = AudioClip(data=b"RIFF....WAVEfmt fake", mime_type="audio/wav", duration_ms=4000)
HINTS = TranscriptionHints(expected_languages=[Language.HINGLISH], keywords=["khoj", "NMMS"])


def answer(
    transcript: str = "aaj munni ne parchhai dekhi", duration_ms: int = 4000
) -> dict[str, object]:
    return {
        "sessionId": "s-1",
        "transcript": transcript,
        "audioDurationMs": duration_ms,
        "turns": [],
    }


class Harness:
    def __init__(self, transcriber: MuseVoiceTranscriber, sleeper: FakeSleeper) -> None:
        self.transcriber = transcriber
        self.sleeper = sleeper


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    clock = FixedClock(NOW)
    sleeper = FakeSleeper(clock)
    retry = RetryPolicy(
        timing=RetryTiming(),
        clock=clock,
        sleeper=sleeper,
        rng=random.Random(7),  # noqa: S311  # deterministic jitter for tests, not cryptography
    )
    config = TranscriberConfig(
        base_url=BASE,
        api_key=SecretStr("test-model-key"),
        model="muse-voice-transcribe-1.0",
        timeout_s=10,
    )
    transcriber = MuseVoiceTranscriber(
        config=config, retry=retry, clock=clock, http=httpx.AsyncClient()
    )
    yield Harness(transcriber, sleeper)
    await transcriber.aclose()


def multipart_parts(request: httpx.Request) -> dict[str, tuple[str, bytes]]:
    """The multipart body as {part name: (content type, content)}."""
    boundary = request.headers["content-type"].split("boundary=")[1].encode()
    parts: dict[str, tuple[str, bytes]] = {}
    for raw_part in request.content.split(b"--" + boundary)[1:-1]:
        head, _, content = raw_part.strip(b"\r\n").partition(b"\r\n\r\n")
        headers = head.decode().split("\r\n")
        name = (
            next(h for h in headers if h.startswith("Content-Disposition"))
            .split('name="')[1]
            .split('"')[0]
        )
        content_type = next((h.split(": ")[1] for h in headers if h.startswith("Content-Type")), "")
        parts[name] = (content_type, content)
    return parts


@respx.mock
async def test_the_request_is_the_documented_multipart_with_bearer_and_accept(
    harness: Harness,
) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=answer()))
    await harness.transcriber.transcribe(WAV, HINTS)
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer test-model-key"
    assert request.headers["accept"] == "application/json"
    assert request.url.params["sessionId"]
    parts = multipart_parts(request)
    assert parts["audio"] == ("audio/wav", WAV.data)
    content_type, request_json = parts["request"]
    assert content_type == "application/json"
    assert json.loads(request_json) == {
        "model": "muse-voice-transcribe-1.0",
        "audioEncoding": "WAV",
        "mode": "PUSH_TO_TALK",
        "keywords": ["khoj", "NMMS"],
        "languageBias": ["Hindi", "English"],
    }


@pytest.mark.parametrize(
    ("languages", "bias"),
    [
        ([Language.HINDI], ["Hindi"]),
        ([Language.ENGLISH], ["English"]),
        ([Language.HINDI, Language.HINGLISH, Language.ENGLISH], ["Hindi", "English"]),
    ],
)
@respx.mock
async def test_language_bias_names_each_language_once(
    harness: Harness, languages: list[Language], bias: list[str]
) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=answer()))
    await harness.transcriber.transcribe(
        WAV, TranscriptionHints(expected_languages=languages, keywords=[])
    )
    assert json.loads(multipart_parts(route.calls[0].request)["request"][1])["languageBias"] == bias


@pytest.mark.parametrize(
    ("transcript", "language"),
    [
        ("aaj munni ne parchhai dekhi, kya karein", Language.HINGLISH),
        ("आज मुन्नी ने परछाई देखी", Language.HINDI),
        ("She watched the shadow move today", Language.ENGLISH),
        ("12 3", None),  # no letters: no language
    ],
)
@respx.mock
async def test_the_language_comes_from_the_words_and_confidence_is_none(
    harness: Harness, transcript: str, language: Language | None
) -> None:
    respx.post(URL).mock(return_value=httpx.Response(200, json=answer(transcript)))
    result, _ = await harness.transcriber.transcribe(WAV, HINTS)
    assert result.text == transcript
    assert result.language is language
    assert result.confidence is None
    assert result.audio_duration_ms == 4000


@pytest.mark.parametrize("transcript", ["", "   ", "\n"])
@respx.mock
async def test_an_empty_transcript_comes_back_empty_not_as_an_error(
    harness: Harness, transcript: str
) -> None:
    respx.post(URL).mock(return_value=httpx.Response(200, json=answer(transcript)))
    result, _ = await harness.transcriber.transcribe(WAV, HINTS)
    assert result.text == ""
    assert result.language is None


@pytest.mark.parametrize(
    ("duration_ms", "seconds", "cost"),
    [
        (15_999, Decimal(15), Decimal("0.000750")),  # billed in whole seconds, rounded down
        (999, Decimal(0), Decimal("0.000000")),
        (180_000, Decimal(180), Decimal("0.009000")),
    ],
)
@respx.mock
async def test_usage_bills_whole_seconds_at_018_per_hour(
    harness: Harness, duration_ms: int, seconds: Decimal, cost: Decimal
) -> None:
    respx.post(URL).mock(return_value=httpx.Response(200, json=answer(duration_ms=duration_ms)))
    _, usage = await harness.transcriber.transcribe(WAV, HINTS)
    assert usage.audio_seconds == seconds
    assert usage.cost_usd == cost
    assert (usage.provider, usage.model) == ("meta_model_api", "muse-voice-transcribe-1.0")


@respx.mock
async def test_extra_response_fields_are_ignored(harness: Harness) -> None:
    respx.post(URL).mock(return_value=httpx.Response(200, json={**answer(), "newField": {"x": 1}}))
    result, _ = await harness.transcriber.transcribe(WAV, HINTS)
    assert result.text == "aaj munni ne parchhai dekhi"


@pytest.mark.parametrize(
    "body",
    [
        b"Transcription complete!",
        b"{}",
        b'{"sessionId": "s", "transcript": 5, "audioDurationMs": 1}',
    ],
    ids=["prose", "empty-object", "wrong-type"],
)
@respx.mock
async def test_a_malformed_response_is_invalid(harness: Harness, body: bytes) -> None:
    respx.post(URL).mock(return_value=httpx.Response(200, content=body))
    with pytest.raises(ProviderResponseInvalid, match="speech-to-text response unexpected"):
        await harness.transcriber.transcribe(WAV, HINTS)


@pytest.mark.parametrize("status", [400, 401, 406, 413])
@respx.mock
async def test_a_4xx_is_rejected_and_not_retried(harness: Harness, status: int) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(status))
    with pytest.raises(ProviderRejected, match=f"speech-to-text http {status}"):
        await harness.transcriber.transcribe(WAV, HINTS)
    assert route.call_count == 1


@respx.mock
async def test_a_500_is_retried_then_succeeds(harness: Harness) -> None:
    route = respx.post(URL).mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json=answer())]
    )
    result, _ = await harness.transcriber.transcribe(WAV, HINTS)
    assert result.text
    assert route.call_count == 2


@respx.mock
async def test_a_429_honours_retry_after(harness: Harness) -> None:
    respx.post(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json=answer()),
        ]
    )
    await harness.transcriber.transcribe(WAV, HINTS)
    assert harness.sleeper.waits == [2.0]


@respx.mock
async def test_a_429_without_retry_after_backs_off_and_raises_when_exhausted(
    harness: Harness,
) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(429))
    with pytest.raises(ProviderRateLimited, match="speech-to-text http 429"):
        await harness.transcriber.transcribe(WAV, HINTS)
    assert route.call_count == 3
    assert len(harness.sleeper.waits) == 2


@pytest.mark.parametrize(
    ("failure", "error", "message"),
    [
        (httpx.ReadTimeout("slow"), ProviderTimeout, "speech-to-text timed out"),
        (httpx.ConnectError("refused"), ProviderUnavailable, "speech-to-text failed: ConnectError"),
    ],
)
@respx.mock
async def test_network_failures_are_typed(
    harness: Harness, failure: httpx.HTTPError, error: type[Exception], message: str
) -> None:
    respx.post(URL).mock(side_effect=failure)
    with pytest.raises(error, match=message):
        await harness.transcriber.transcribe(WAV, HINTS)


async def test_audio_that_isnt_wav_is_refused_before_any_call(harness: Harness) -> None:
    ogg = AudioClip(data=b"OggS", mime_type="audio/ogg; codecs=opus", duration_ms=None)
    with pytest.raises(ValueError, match="takes audio/wav, got audio/ogg"):
        await harness.transcriber.transcribe(ogg, HINTS)


def test_a_model_without_a_listed_price_is_refused_at_startup() -> None:
    clock = FixedClock(NOW)
    retry = RetryPolicy(
        timing=RetryTiming(),
        clock=clock,
        sleeper=FakeSleeper(clock),
        rng=random.Random(7),  # noqa: S311  # deterministic jitter for tests, not cryptography
    )
    config = TranscriberConfig(
        base_url=BASE, api_key=SecretStr("k"), model="muse-voice-2", timeout_s=10
    )
    with pytest.raises(ConfigError, match="no price listed for speech-to-text model muse-voice-2"):
        MuseVoiceTranscriber(config=config, retry=retry, clock=clock)
