"""FallbackLanguageModel: Muse Spark Open first for some prompts, Muse Spark 1.3 if it fails
(s10b §4.8, decision C9).

A request whose model is the Open model goes to the Open adapter within `primary_timeout`
(owner, 2026-10-27: 7 s; spike E measured 5.8 s p50, 7.7 s p95). On any provider error or
timeout it's sent again to the fallback with the fallback model id. Everything else goes
straight to the fallback. The StepUsage of whichever model answered is what's returned.

While the Open model keeps failing, its breaker skips it (owner, 2026-11-01): the request goes
straight to the fallback instead of waiting out the 7 s limit each time. It is tried again when
the breaker closes on its own; there is no probe, which would cost a generation.
"""

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from pydantic import BaseModel

from app.core.errors import ProviderError
from app.core.logging import get_logger
from app.core.provider_breaker import ProviderBreaker
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
        self,
        primary: LanguageModel,
        fallback: LanguageModel,
        route: FallbackRoute,
        breaker: ProviderBreaker | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._route = route
        self._breaker = breaker

    async def generate[OutputT: BaseModel](
        self, request: GenerationRequest[OutputT]
    ) -> GenerationResult[OutputT]:
        if request.model != self._route.primary_model:
            return await self._fallback.generate(request)
        if self._breaker is None or not self._breaker.is_open():
            try:
                async with asyncio.timeout(self._route.primary_timeout.total_seconds()):
                    answer = await self._primary.generate(request)
            except (ProviderError, TimeoutError) as exc:
                logger.warning(
                    "open_model_fallback",
                    prompt_id=request.prompt.prompt_id,
                    error=type(exc).__name__,
                )
                if self._breaker is not None:
                    self._breaker.failed()
            else:
                if self._breaker is not None:
                    self._breaker.succeeded()
                return answer
        fallback_request = request.model_copy(update={"model": self._route.fallback_model})
        return await self._fallback.generate(fallback_request)
