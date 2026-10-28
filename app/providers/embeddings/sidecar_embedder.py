"""SidecarEmbedder: multilingual-e5-small vectors from the voice server's `/embed` (s11 §4.4).

The e5 prefixes are added here ("query: " / "passage: "), so callers pass raw text. Texts go in
batches of at most 32. Every reply is checked: the model it names, one 384-number vector per
text. The voice server is ours (no per-call cost), so nothing is billed.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import ClassVar

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from app.core.clock import Clock
from app.core.errors import (
    ProviderRejected,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.domain.enums import EmbedPurpose
from app.providers.http import RetryPolicy

PROVIDER = "ml_sidecar"


class _EmbedReply(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    model: str
    dimensions: int
    vectors: list[list[float]]


@dataclass(frozen=True, slots=True)
class EmbedderConfig:
    base_url: str  # SIDECAR_BASE_URL
    token: SecretStr  # SIDECAR_TOKEN
    model: str  # EMBED_MODEL
    timeout_s: float  # TIMEOUT_EMBED_S


class SidecarEmbedder:
    """Satisfies `Embedder`."""

    DIMENSIONS: ClassVar[int] = 384
    BATCH: ClassVar[int] = 32
    PREFIXES: ClassVar[dict[EmbedPurpose, str]] = {
        EmbedPurpose.QUERY: "query: ",
        EmbedPurpose.PASSAGE: "passage: ",
    }

    def __init__(
        self,
        *,
        config: EmbedderConfig,
        retry: RetryPolicy,
        clock: Clock,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._retry = retry
        self._clock = clock
        self._http = http if http is not None else httpx.AsyncClient()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def embed(self, texts: Sequence[str], purpose: EmbedPurpose) -> list[list[float]]:
        """Raises ProviderError; ProviderResponseInvalid when a reply doesn't match the model."""
        prefix = self.PREFIXES[purpose]
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.BATCH):
            batch = [f"{prefix}{text}" for text in texts[start : start + self.BATCH]]
            vectors.extend(await self._embed_batch(batch))
        return vectors

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        deadline = self._clock.now() + timedelta(seconds=self._config.timeout_s)
        reply = await self._retry.run(lambda: self._post(batch), deadline=deadline)
        return self._checked(reply, len(batch))

    def _checked(self, reply: _EmbedReply, expected: int) -> list[list[float]]:
        if reply.model != self._config.model:
            raise ProviderResponseInvalid(
                f"embed server runs {reply.model}, expected {self._config.model}", provider=PROVIDER
            )
        if len(reply.vectors) != expected:
            raise ProviderResponseInvalid(
                f"embed server returned {len(reply.vectors)} vectors for {expected}",
                provider=PROVIDER,
            )
        if any(len(vector) != self.DIMENSIONS for vector in reply.vectors):
            raise ProviderResponseInvalid(
                f"embed server returned vectors that aren't {self.DIMENSIONS} long",
                provider=PROVIDER,
            )
        return reply.vectors

    async def _post(self, texts: list[str]) -> _EmbedReply:
        try:
            response = await self._http.post(
                f"{self._config.base_url.rstrip('/')}/embed",
                json={"texts": texts},
                headers={"Authorization": f"Bearer {self._config.token.get_secret_value()}"},
                timeout=self._config.timeout_s,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("embed server timed out", provider=PROVIDER) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(
                f"embed server unreachable: {type(exc).__name__}", provider=PROVIDER
            ) from exc
        if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            raise ProviderUnavailable(
                f"embed server http {response.status_code}", provider=PROVIDER
            )
        if not response.is_success:
            raise ProviderRejected(f"embed server http {response.status_code}", provider=PROVIDER)
        try:
            return _EmbedReply.model_validate_json(response.content)
        except ValidationError as exc:
            raise ProviderResponseInvalid(
                "embed server reply isn't the /embed shape", provider=PROVIDER
            ) from exc
