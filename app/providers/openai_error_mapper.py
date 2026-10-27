"""OpenAiErrorMapper: an openai SDK exception → our ProviderError (s05 §4.1, contracts §4).

Shared by every adapter that talks to an OpenAI-compatible host (Meta Model API, Groq). Messages
carry the exception's type and HTTP status, never request or response text.
"""

import math

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)

from app.core.errors import (
    ProviderError,
    ProviderRateLimited,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnavailable,
)


class OpenAiErrorMapper:
    @staticmethod
    def map(error: APIError, *, label: str, provider: str) -> ProviderError:
        described = f"{label}: {type(error).__name__}"
        if isinstance(error, APITimeoutError):
            return ProviderTimeout(f"{described} timed out", provider=provider)
        if isinstance(error, RateLimitError):
            return ProviderRateLimited(
                f"{described} rate limited",
                provider=provider,
                retry_after=OpenAiErrorMapper.retry_after(error),
            )
        if isinstance(error, APIConnectionError | InternalServerError):
            return ProviderUnavailable(f"{described} unavailable", provider=provider)
        if isinstance(error, APIStatusError):
            return ProviderRejected(
                f"{described} rejected: HTTP {error.status_code}", provider=provider
            )
        return ProviderUnavailable(f"{described} failed", provider=provider)

    @staticmethod
    def retry_after(error: RateLimitError) -> float | None:
        """Seconds from a numeric Retry-After header; None when absent or not a number."""
        header = error.response.headers.get("retry-after")
        if header is None:
            return None
        try:
            seconds = float(header)
        except ValueError:
            return None
        if not math.isfinite(seconds):
            return None
        return max(seconds, 0.0)
