"""FallbackLanguageModel: Muse Spark Open first for some prompts, Muse Spark 1.3 if it fails
(s10b §4.8, decision C9).

A request whose model is the Open model goes to the Open adapter within `primary_timeout`
(owner, 2026-10-27: 7 s; spike E measured 5.8 s p50, 7.7 s p95). On any provider error or
timeout it's sent again to the fallback with the fallback model id. Everything else goes
straight to the fallback. The StepUsage of whichever model answered is what's returned.
"""

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from pydantic import BaseModel

from app.core.errors import ProviderError
from app.core.logging import get_logger
from app.providers.ports import GenerationRequest, GenerationResult, LanguageModel

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class FallbackRoute:
    primary_model: str  # OPEN_MODEL
    fallback_model: str  # MODEL_TEXT
    primary_timeout: timedelta  # TIMEOUT_OPEN_MODEL_S


class FallbackLanguageModel:
    """Satisfies `LanguageModel`."""

    def __init__(
        self, primary: LanguageModel, fallback: LanguageModel, route: FallbackRoute
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._route = route

    async def generate[OutputT: BaseModel](
        self, request: GenerationRequest[OutputT]
    ) -> GenerationResult[OutputT]:
        if request.model != self._route.primary_model:
            return await self._fallback.generate(request)
        try:
            async with asyncio.timeout(self._route.primary_timeout.total_seconds()):
                return await self._primary.generate(request)
        except (ProviderError, TimeoutError) as exc:
            logger.warning(
                "open_model_fallback",
                prompt_id=request.prompt.prompt_id,
                error=type(exc).__name__,
            )
        fallback_request = request.model_copy(update={"model": self._route.fallback_model})
        return await self._fallback.generate(fallback_request)
