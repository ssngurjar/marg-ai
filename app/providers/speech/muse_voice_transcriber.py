"""MuseVoiceTranscriber: a voice note's words, from Muse Voice Transcribe (s06 §4.5).

One multipart POST: a `request` JSON part and the 16 kHz mono WAV. The response has no language
and no confidence: the language comes from RegisterDetector, and confidence is None. An empty
transcript is returned as is; the pipeline treats it as "nothing said", not as a failure.
"""

import json
import math
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import ClassVar
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from app.constants.model_prices import STT_PRICE_PER_HOUR
from app.core.clock import Clock
from app.core.errors import (
    ConfigError,
    ProviderError,
    ProviderRateLimited,
    ProviderRejected,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.domain.enums import Language
from app.domain.models.message import AudioClip, Transcript
from app.domain.models.usage import StepUsage
from app.domain.rules.register_detector import RegisterDetector
from app.providers.http import RetryPolicy
from app.providers.ports import TranscriptionHints

PROVIDER = "meta_model_api"


class _TranscribeResponse(BaseModel):
    """Only the fields we read; new fields from the provider must not break us."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    sessionId: str  # noqa: N815 (the provider's field name)
    transcript: str
    audioDurationMs: int  # noqa: N815 (the provider's field name)


@dataclass(frozen=True, slots=True)
class TranscriberConfig:
    base_url: str  # MODEL_API_BASE_URL, ending in /v1
    api_key: SecretStr
    model: str  # MODEL_STT
    timeout_s: float  # TIMEOUT_STT_S


class MuseVoiceTranscriber:
    """Satisfies `Transcriber`."""

    PROVIDER_LANGUAGE_NAMES: ClassVar[dict[Language, tuple[str, ...]]] = {
        Language.HINDI: ("Hindi",),
        Language.HINGLISH: ("Hindi", "English"),
        Language.ENGLISH: ("English",),
    }
    MILLISECONDS_PER_HOUR: ClassVar[Decimal] = Decimal(3_600_000)
    COST_PLACES: ClassVar[Decimal] = Decimal("0.000001")

    def __init__(
        self,
        *,
        config: TranscriberConfig,
        retry: RetryPolicy,
        clock: Clock,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        if config.model not in STT_PRICE_PER_HOUR:
            raise ConfigError(f"no price listed for speech-to-text model {config.model}")
        self._config = config
        self._price_per_hour = STT_PRICE_PER_HOUR[config.model]
        self._retry = retry
        self._clock = clock
        self._http = http if http is not None else httpx.AsyncClient()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def transcribe(
        self, clip: AudioClip, hints: TranscriptionHints
    ) -> tuple[Transcript, StepUsage]:
        if clip.mime_type != "audio/wav":
            raise ValueError(f"MuseVoiceTranscriber takes audio/wav, got {clip.mime_type}")
        request_part = json.dumps(
            {
                "model": self._config.model,
                "audioEncoding": "WAV",
                "mode": "PUSH_TO_TALK",
                "keywords": hints.keywords,
                "languageBias": self._language_bias(hints.expected_languages),
            }
        )
        session_id = str(uuid4())
        deadline = self._clock.now() + timedelta(seconds=self._config.timeout_s)
        response = await self._retry.run(
            lambda: self._post(session_id, request_part, clip.data), deadline=deadline
        )
        transcript = Transcript(
            text=response.transcript.strip(),
            language=RegisterDetector.detect(response.transcript),
            confidence=None,
            audio_duration_ms=response.audioDurationMs,
        )
        return transcript, self._usage(response.audioDurationMs)

    @staticmethod
    def _language_bias(languages: list[Language]) -> list[str]:
        names: list[str] = []
        for language in languages:
            for name in MuseVoiceTranscriber.PROVIDER_LANGUAGE_NAMES[language]:
                if name not in names:
                    names.append(name)
        return names

    async def _post(self, session_id: str, request_part: str, wav: bytes) -> _TranscribeResponse:
        url = f"{self._config.base_url.rstrip('/')}/asr/transcribe"
        try:
            response = await self._http.post(
                url,
                params={"sessionId": session_id},
                headers={
                    "Authorization": f"Bearer {self._config.api_key.get_secret_value()}",
                    "Accept": "application/json",
                },
                files={
                    "request": (None, request_part, "application/json"),
                    "audio": ("voice.wav", wav, "audio/wav"),
                },
                timeout=self._config.timeout_s,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("speech-to-text timed out", provider=PROVIDER) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(
                f"speech-to-text failed: {type(exc).__name__}", provider=PROVIDER
            ) from exc
        if not response.is_success:
            raise self._status_error(response)
        try:
            return _TranscribeResponse.model_validate_json(response.content)
        except ValidationError as exc:
            raise ProviderResponseInvalid(
                "speech-to-text response unexpected", provider=PROVIDER
            ) from exc

    @staticmethod
    def _status_error(response: httpx.Response) -> ProviderError:
        status = response.status_code
        label = f"speech-to-text http {status}"
        if status == httpx.codes.TOO_MANY_REQUESTS:
            return ProviderRateLimited(
                label,
                provider=PROVIDER,
                retry_after=MuseVoiceTranscriber._retry_after(response.headers.get("retry-after")),
            )
        if status >= httpx.codes.INTERNAL_SERVER_ERROR:
            return ProviderUnavailable(label, provider=PROVIDER)
        return ProviderRejected(label, provider=PROVIDER)

    @staticmethod
    def _retry_after(header: str | None) -> float | None:
        """Seconds from a numeric Retry-After header; None when absent or not a number."""
        if header is None:
            return None
        try:
            seconds = float(header)
        except ValueError:
            return None
        if not math.isfinite(seconds):
            return None
        return max(seconds, 0.0)

    def _usage(self, audio_duration_ms: int) -> StepUsage:
        """Billed in whole seconds, rounded down (s06 §4.5)."""
        audio_seconds = Decimal(audio_duration_ms // 1000)
        cost = (audio_seconds * 1000 * self._price_per_hour / self.MILLISECONDS_PER_HOUR).quantize(
            self.COST_PLACES, rounding=ROUND_HALF_UP
        )
        return StepUsage(
            provider=PROVIDER,
            model=self._config.model,
            input_tokens=None,
            output_tokens=None,
            audio_seconds=audio_seconds,
            cost_usd=cost,
        )
