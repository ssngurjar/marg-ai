"""SidecarSynthesizer: a reply's spoken text as a WhatsApp voice note (s06 §4.7).

The text is prepared by TtsTextPreparer (script check, sentences), spoken by the voice server's
`/tts` (the separate marg-ai-tts project), and converted to OGG/Opus by AudioTranscoder. One
adapter serves both engines (C8): `TTS_ENGINE` says which one the voice server runs, and a
server running the other engine answers 422. The voice server costs nothing per request (local
or rented by the hour), so the recorded cost is 0.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import ClassVar, TypedDict

import httpx
from pydantic import SecretStr

from app.audio.audio_transcoder import AudioTranscoder
from app.audio.tts_text_preparer import TtsTextPreparer, Voice
from app.core.clock import Clock
from app.core.errors import (
    ProviderRejected,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.core.types import TtsEngine
from app.domain.enums import Language
from app.domain.models.message import AudioClip
from app.domain.models.usage import StepUsage
from app.providers.http import RetryPolicy

PROVIDER = "ml_sidecar"


class _TtsBody(TypedDict):
    """The voice server's request (s06 §4.9)."""

    engine: TtsEngine
    voice: Voice
    sentences: list[str]


@dataclass(frozen=True, slots=True)
class SidecarConfig:
    base_url: str  # SIDECAR_BASE_URL
    token: SecretStr  # SIDECAR_TOKEN
    engine: TtsEngine  # TTS_ENGINE
    timeout_s: float  # TIMEOUT_SYNTHESIZE_S


class SidecarSynthesizer:
    """Satisfies `Synthesizer`."""

    MODELS: ClassVar[dict[TtsEngine, dict[Voice, str]]] = {
        "mms": {"hin": "facebook/mms-tts-hin", "eng": "facebook/mms-tts-eng"},
        "indic_parler": {"hin": "ai4bharat/indic-parler-tts", "eng": "ai4bharat/indic-parler-tts"},
    }
    DURATION_HEADER: ClassVar[str] = "x-audio-duration-ms"

    def __init__(
        self,
        *,
        config: SidecarConfig,
        transcoder: AudioTranscoder,
        retry: RetryPolicy,
        clock: Clock,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._transcoder = transcoder
        self._retry = retry
        self._clock = clock
        self._http = http if http is not None else httpx.AsyncClient()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def synthesize(self, text: str, language: Language) -> tuple[AudioClip, StepUsage]:
        """Raises TtsTextInvalid when the text can't be spoken well (the reply goes as text)."""
        prepared = TtsTextPreparer.prepare(text, language)
        body: _TtsBody = {
            "engine": self._config.engine,
            "voice": prepared.voice,
            "sentences": list(prepared.sentences),
        }
        deadline = self._clock.now() + timedelta(seconds=self._config.timeout_s)
        speech = await self._retry.run(lambda: self._post(body), deadline=deadline)
        voice_note = await self._transcoder.to_voice_note(speech)
        usage = StepUsage(
            provider=PROVIDER,
            model=self.MODELS[self._config.engine][prepared.voice],
            input_tokens=None,
            output_tokens=None,
            audio_seconds=Decimal(speech.duration_ms or 0) / 1000,
            cost_usd=Decimal("0"),
        )
        return voice_note, usage

    async def _post(self, body: _TtsBody) -> AudioClip:
        try:
            response = await self._http.post(
                f"{self._config.base_url.rstrip('/')}/tts",
                json=body,
                headers={"Authorization": f"Bearer {self._config.token.get_secret_value()}"},
                timeout=self._config.timeout_s,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("voice server timed out", provider=PROVIDER) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(
                f"voice server unreachable: {type(exc).__name__}", provider=PROVIDER
            ) from exc
        if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            raise ProviderUnavailable(
                f"voice server http {response.status_code}", provider=PROVIDER
            )
        if not response.is_success:
            # 401: wrong SIDECAR_TOKEN. 422: the server runs the other engine, or a bad request.
            raise ProviderRejected(f"voice server http {response.status_code}", provider=PROVIDER)
        return AudioClip(
            data=response.content,
            mime_type=self._wav_type(response),
            duration_ms=self._duration_ms(response),
        )

    @staticmethod
    def _wav_type(response: httpx.Response) -> str:
        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("audio/wav") or not response.content.startswith(b"RIFF"):
            raise ProviderResponseInvalid("voice server didn't return a wav", provider=PROVIDER)
        return "audio/wav"

    @staticmethod
    def _duration_ms(response: httpx.Response) -> int:
        header = response.headers.get(SidecarSynthesizer.DURATION_HEADER)
        if header is None or not header.isdigit() or int(header) == 0:
            raise ProviderResponseInvalid("voice server sent no audio duration", provider=PROVIDER)
        return int(header)
