"""HttpHealthCheck: is a provider's API answering, for `/readyz` (s16 §4.3).

One authenticated GET to a cheap endpoint (the model list, the voice server's health page). It
never logs or returns the response body, and its error names the provider only: a URL can
carry tokens.
"""

from dataclasses import dataclass
from typing import Final

import httpx
from pydantic import SecretStr

from app.core.errors import ProviderUnavailable

HTTP_OK: Final = 200


@dataclass(frozen=True, slots=True)
class HealthEndpoint:
    provider: str  # e.g. "meta_model_api": names the failure
    url: str
    token: SecretStr
    timeout_s: float


class HttpHealthCheck:
    def __init__(self, endpoint: HealthEndpoint) -> None:
        self._endpoint = endpoint
        self._client = httpx.AsyncClient(timeout=endpoint.timeout_s)

    async def check(self) -> None:
        """Raises ProviderUnavailable unless the endpoint answers 200."""
        endpoint = self._endpoint
        headers = {"Authorization": f"Bearer {endpoint.token.get_secret_value()}"}
        try:
            response = await self._client.get(endpoint.url, headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(
                f"{endpoint.provider} health: {type(exc).__name__}", provider=endpoint.provider
            ) from exc
        if response.status_code != HTTP_OK:
            raise ProviderUnavailable(
                f"{endpoint.provider} health: http {response.status_code}",
                provider=endpoint.provider,
            )

    async def aclose(self) -> None:
        await self._client.aclose()
