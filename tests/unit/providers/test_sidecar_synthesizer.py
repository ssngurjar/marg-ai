"""SidecarSynthesizer against a faked voice server, with the real ffmpeg (s06 §4.7, §9)."""

import io
import json
import math
import random
import wave
from array import array
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.audio.audio_transcoder import VOICE_NOTE_MIME, AudioTranscoder
from app.core.errors import (
    ProviderRejected,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
    TtsTextInvalid,
)
from app.core.types import TtsEngine
from app.domain.enums import Language
from app.providers.http import RetryPolicy, RetryTiming
from app.providers.speech.sidecar_synthesizer import SidecarConfig, SidecarSynthesizer
from tests.fakes.clock import FixedClock
from tests.fakes.sleeper import FakeSleeper

pytestmark = pytest.mark.unit

BASE = "http://voice.test"
URL = f"{BASE}/tts"
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
HINDI_REPLY = "आज मुन्नी के साथ एक खोज करते हैं। मुन्नी से पूछिए, परछाई कहाँ गई?"


def speech_wav(duration_ms: int = 1200, rate: int = 16000) -> bytes:
    count = rate * duration_ms // 1000
    samples = array("h", (int(6000 * math.sin(2 * math.pi * 200 * n / rate)) for n in range(count)))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(samples.tobytes())
    return buffer.getvalue()


def spoken(duration_ms: int = 1200) -> httpx.Response:
    return httpx.Response(
        200,
        content=speech_wav(duration_ms),
        headers={"content-type": "audio/wav", "x-audio-duration-ms": str(duration_ms)},
    )


class Harness:
    def __init__(self, synthesizer: SidecarSynthesizer, sleeper: FakeSleeper) -> None:
        self.synthesizer = synthesizer
        self.sleeper = sleeper


@pytest.fixture
async def harness_for() -> AsyncIterator[dict[TtsEngine, Harness]]:
    built: dict[TtsEngine, Harness] = {}
    for engine in ("kokoro",):
        clock = FixedClock(NOW)
        sleeper = FakeSleeper(clock)
        retry = RetryPolicy(
            timing=RetryTiming(),
            clock=clock,
            sleeper=sleeper,
            rng=random.Random(7),  # noqa: S311  # deterministic jitter for tests, not cryptography
        )
        synthesizer = SidecarSynthesizer(
            config=SidecarConfig(BASE, SecretStr("test-sidecar-token"), engine, timeout_s=8),
            transcoder=AudioTranscoder(timeout_s=10),
            retry=retry,
            clock=clock,
            http=httpx.AsyncClient(),
        )
        built[engine] = Harness(synthesizer, sleeper)
    yield built
    for harness in built.values():
        await harness.synthesizer.aclose()


@pytest.fixture
def harness(harness_for: dict[TtsEngine, Harness]) -> Harness:
    return harness_for["kokoro"]


@pytest.mark.parametrize(
    ("engine", "language", "voice", "model"),
    [
        ("kokoro", Language.HINDI, "hin", "hexgrad/Kokoro-82M"),
        ("kokoro", Language.HINGLISH, "hin", "hexgrad/Kokoro-82M"),
        ("kokoro", Language.ENGLISH, "eng", "hexgrad/Kokoro-82M"),
    ],
)
@respx.mock
async def test_the_engine_setting_picks_what_is_asked_for_and_recorded(
    harness_for: dict[TtsEngine, Harness],
    engine: TtsEngine,
    language: Language,
    voice: str,
    model: str,
) -> None:
    route = respx.post(URL).mock(return_value=spoken())
    text = "Well done! Ask her why." if language is Language.ENGLISH else HINDI_REPLY
    _, usage = await harness_for[engine].synthesizer.synthesize(text, language)
    body = json.loads(route.calls[0].request.content)
    assert body["engine"] == engine
    assert body["voice"] == voice
    assert usage.model == model
    assert (usage.provider, usage.cost_usd) == ("ml_sidecar", Decimal("0"))


@respx.mock
async def test_a_reply_becomes_an_ogg_opus_voice_note_from_prepared_sentences(
    harness: Harness,
) -> None:
    route = respx.post(URL).mock(return_value=spoken(1200))
    clip, usage = await harness.synthesizer.synthesize(HINDI_REPLY, Language.HINGLISH)
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer test-sidecar-token"
    assert json.loads(request.content)["sentences"] == [
        "आज मुन्नी के साथ एक खोज करते हैं।",
        "मुन्नी से पूछिए, परछाई कहाँ गई?",
    ]
    assert clip.mime_type == VOICE_NOTE_MIME
    assert clip.data.startswith(b"OggS")
    assert clip.duration_ms == 1200
    assert usage.audio_seconds == Decimal("1.2")


@pytest.mark.parametrize(
    ("text", "language", "message"),
    [
        ("Aaj ek khoj karte hain.", Language.HINGLISH, "non-devanagari"),
        ("🙂🙂", Language.HINDI, "nothing speakable"),
        ("", Language.HINDI, "nothing speakable"),
        ("आज " * 500, Language.HINDI, "too long"),
    ],
)
@respx.mock
async def test_text_that_cant_be_spoken_well_never_reaches_the_server(
    harness: Harness, text: str, language: Language, message: str
) -> None:
    route = respx.post(URL).mock(return_value=spoken())
    with pytest.raises(TtsTextInvalid, match=message):
        await harness.synthesizer.synthesize(text, language)
    assert route.call_count == 0


@pytest.mark.parametrize("status", [401, 422])
@respx.mock
async def test_a_wrong_token_or_the_other_engine_is_rejected_without_retry(
    harness: Harness, status: int
) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(status))
    with pytest.raises(ProviderRejected, match=f"voice server http {status}"):
        await harness.synthesizer.synthesize(HINDI_REPLY, Language.HINDI)
    assert route.call_count == 1


@respx.mock
async def test_a_5xx_is_retried_then_succeeds(harness: Harness) -> None:
    route = respx.post(URL).mock(side_effect=[httpx.Response(503), spoken()])
    clip, _ = await harness.synthesizer.synthesize(HINDI_REPLY, Language.HINDI)
    assert clip.data.startswith(b"OggS")
    assert route.call_count == 2


@respx.mock
async def test_a_server_that_stays_down_is_unavailable_after_the_retries(harness: Harness) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(500))
    with pytest.raises(ProviderUnavailable, match="voice server http 500"):
        await harness.synthesizer.synthesize(HINDI_REPLY, Language.HINDI)
    assert route.call_count == 3


@pytest.mark.parametrize(
    ("failure", "error", "message"),
    [
        (httpx.ReadTimeout("slow"), ProviderTimeout, "voice server timed out"),
        (
            httpx.ConnectError("refused"),
            ProviderUnavailable,
            "voice server unreachable: ConnectError",
        ),
    ],
)
@respx.mock
async def test_network_failures_are_typed(
    harness: Harness, failure: httpx.HTTPError, error: type[Exception], message: str
) -> None:
    respx.post(URL).mock(side_effect=failure)
    with pytest.raises(error, match=message):
        await harness.synthesizer.synthesize(HINDI_REPLY, Language.HINDI)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(200, json={"ok": True}), "didn't return a wav"),
        (
            httpx.Response(200, content=b"not a wav", headers={"content-type": "audio/wav"}),
            "didn't return a wav",
        ),
        (
            httpx.Response(200, content=speech_wav(), headers={"content-type": "audio/wav"}),
            "no audio duration",
        ),
        (
            httpx.Response(
                200,
                content=speech_wav(),
                headers={"content-type": "audio/wav", "x-audio-duration-ms": "0"},
            ),
            "no audio duration",
        ),
        (
            httpx.Response(
                200,
                content=speech_wav(),
                headers={"content-type": "audio/wav", "x-audio-duration-ms": "-5"},
            ),
            "no audio duration",
        ),
    ],
    ids=["json", "not-riff", "no-duration", "zero-duration", "negative-duration"],
)
@respx.mock
async def test_a_malformed_answer_is_invalid(
    harness: Harness, response: httpx.Response, message: str
) -> None:
    respx.post(URL).mock(return_value=response)
    with pytest.raises(ProviderResponseInvalid, match=message):
        await harness.synthesizer.synthesize(HINDI_REPLY, Language.HINDI)
