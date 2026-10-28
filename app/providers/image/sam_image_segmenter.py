"""SamImageSegmenter: how many of each thing are in a photo, from SAM 3.1 (s10b §4.14, spike F).

One `POST /v1/responses` call per noun phrase (SAM 3.1 takes one phrase at a time), all phrases
at once, each under the shared retry policy within one deadline. The photo goes as a base64
`data:` URL and is never stored. The answer's box tokens are counted by SegmentationOutputParser.
"""

import asyncio
import base64
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from openai import APIError, AsyncOpenAI
from openai.types.responses import Response
from pydantic import SecretStr

from app.constants.model_prices import SEGMENT_PRICE_EACH
from app.core.clock import Clock
from app.core.errors import ConfigError
from app.domain.models.message import ImageClip
from app.domain.models.photo import ObjectCount
from app.domain.models.usage import StepUsage
from app.providers.http import RetryPolicy
from app.providers.image.segmentation_output_parser import SegmentationOutputParser
from app.providers.openai_error_mapper import OpenAiErrorMapper

PROVIDER: Final = "meta_model_api"


@dataclass(frozen=True, slots=True)
class SegmentModelConfig:
    base_url: str  # MODEL_API_BASE_URL
    api_key: SecretStr
    model: str  # MODEL_SEGMENT
    timeout_s: float  # TIMEOUT_ANALYZE_IMAGE_S


class SamImageSegmenter:
    """Satisfies `ImageSegmenter`."""

    def __init__(
        self,
        *,
        config: SegmentModelConfig,
        retry: RetryPolicy,
        clock: Clock,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if config.model not in SEGMENT_PRICE_EACH:
            raise ConfigError(f"no price listed for segmentation model {config.model}")
        self._config = config
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

    async def count(
        self, image: ImageClip, phrases: Sequence[str]
    ) -> tuple[list[ObjectCount], StepUsage]:
        """Raises ProviderError when any phrase's call fails: a partial count is never returned."""
        if not phrases:
            raise ValueError("SamImageSegmenter.count needs at least one phrase")
        deadline = self._clock.now() + timedelta(seconds=self._config.timeout_s)
        image_url = f"data:{image.mime_type};base64,{base64.b64encode(image.data).decode('ascii')}"
        found = await asyncio.gather(
            *(self._count_one(image_url, phrase, deadline) for phrase in phrases)
        )
        counts = [
            ObjectCount(phrase=phrase, count=number)
            for phrase, number in zip(phrases, found, strict=True)
        ]
        cost = SEGMENT_PRICE_EACH[self._config.model] * Decimal(len(phrases))
        usage = StepUsage(
            provider=PROVIDER,
            model=self._config.model,
            input_tokens=None,
            output_tokens=None,
            audio_seconds=None,
            cost_usd=cost,
        )
        return counts, usage

    async def _count_one(self, image_url: str, phrase: str, deadline: datetime) -> int:
        response = await self._retry.run(lambda: self._call(image_url, phrase), deadline=deadline)
        return SegmentationOutputParser.count(response.output_text)

    async def _call(self, image_url: str, phrase: str) -> Response:
        try:
            return await self._client.responses.create(
                model=self._config.model,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": phrase},
                            {"type": "input_image", "image_url": image_url, "detail": "auto"},
                        ],
                    }
                ],
                metadata={"include_confidence": "true", "mask_encoding": "one_bit"},
            )
        except APIError as exc:
            raise OpenAiErrorMapper.map(exc, label="sam", provider=PROVIDER) from exc
