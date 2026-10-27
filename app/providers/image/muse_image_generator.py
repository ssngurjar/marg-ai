"""MuseImageGenerator: khoj card illustrations from Muse Image (s10b §4.13, spike F).

One `POST /v1/images/generations` call (1024x1024 PNG, base64) under the shared retry policy,
at the reasoning strength spike F chose ("low": 0.2 s over the latency bar, same quality). The
PNG (about 5 MB) is returned as an 800-pixel JPEG (about 250 KB) by ImageCompressor.
"""

import base64
import binascii
from dataclasses import dataclass
from datetime import timedelta
from typing import Final, Literal

from openai import APIError, AsyncOpenAI
from openai.types import ImagesResponse
from pydantic import SecretStr

from app.constants.model_prices import IMAGE_PRICE_EACH
from app.core.clock import Clock
from app.core.errors import ConfigError, ProviderResponseInvalid
from app.domain.models.message import ImageClip
from app.domain.models.usage import StepUsage
from app.providers.http import RetryPolicy
from app.providers.image.image_compressor import ImageCompressor
from app.providers.openai_error_mapper import OpenAiErrorMapper

PROVIDER: Final = "meta_model_api"
CARD_SIZE: Final = "1024x1024"
PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True, slots=True)
class ImageModelConfig:
    base_url: str  # MODEL_API_BASE_URL
    api_key: SecretStr
    model: str  # MODEL_IMAGE
    reasoning_strength: Literal["low", "high"]  # IMAGE_REASONING_STRENGTH
    timeout_s: float  # TIMEOUT_MAKE_CARD_S


class MuseImageGenerator:
    """Satisfies `ImageGenerator`."""

    def __init__(
        self,
        *,
        config: ImageModelConfig,
        retry: RetryPolicy,
        clock: Clock,
        compressor: ImageCompressor,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if config.model not in IMAGE_PRICE_EACH:
            raise ConfigError(f"no price listed for image model {config.model}")
        self._config = config
        self._compressor = compressor
        self._retry = retry
        self._clock = clock
        self._client = client or AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key.get_secret_value(),
            timeout=config.timeout_s,
            max_retries=0,
        )

    async def aclose(self) -> None:
        await self._client.close()

    async def generate(self, prompt: str) -> tuple[ImageClip, StepUsage]:
        """Raises ProviderError, or TranscodeFailed when the PNG can't be made a JPEG."""
        deadline = self._clock.now() + timedelta(seconds=self._config.timeout_s)
        response = await self._retry.run(lambda: self._call(prompt), deadline=deadline)
        image = await self._compressor.to_jpeg(MuseImageGenerator._image_of(response))
        usage = StepUsage(
            provider=PROVIDER,
            model=self._config.model,
            input_tokens=None,
            output_tokens=None,
            audio_seconds=None,
            cost_usd=IMAGE_PRICE_EACH[self._config.model],
        )
        return image, usage

    async def _call(self, prompt: str) -> ImagesResponse:
        try:
            return await self._client.images.generate(
                model=self._config.model,
                prompt=prompt,
                n=1,
                size=CARD_SIZE,
                response_format="b64_json",
                output_format="png",
                extra_body={"reasoning_strength": self._config.reasoning_strength},
            )
        except APIError as exc:
            raise OpenAiErrorMapper.map(exc, label="muse image", provider=PROVIDER) from exc

    @staticmethod
    def _image_of(response: ImagesResponse) -> ImageClip:
        images = response.data or []
        encoded = images[0].b64_json if images else None
        if not encoded:
            raise ProviderResponseInvalid("muse image returned no image", provider=PROVIDER)
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ProviderResponseInvalid(
                "muse image returned undecodable data", provider=PROVIDER
            ) from exc
        if not data.startswith(PNG_SIGNATURE):
            raise ProviderResponseInvalid("muse image returned no PNG", provider=PROVIDER)
        return ImageClip(data=data, mime_type="image/png")
