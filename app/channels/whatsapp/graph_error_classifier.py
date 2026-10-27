"""GraphErrorClassifier: a failed Graph API response mapped to our error types (s03 §4.10). Pure."""

import httpx
from pydantic import ValidationError

from app.channels.whatsapp.payloads import GraphErrorEnvelope
from app.constants.whatsapp import (
    PROVIDER,
    RATE_LIMIT_CODES,
    TRANSIENT_CODES,
)
from app.core.errors import (
    ProviderError,
    ProviderRateLimited,
    ProviderRejected,
    ProviderUnavailable,
)


class GraphErrorClassifier:
    @staticmethod
    def classify(status_code: int, body: bytes) -> ProviderError:
        """Map a failed Graph API response to our error types, by Meta's error code (s03 §4.10).

        Codes verified against Meta's error-code reference on 2026-10-27.
        """
        code: int | None = None
        try:
            code = GraphErrorEnvelope.model_validate_json(body).error.code
        except ValidationError:
            code = None
        label = f"graph api error {code}" if code is not None else f"graph api http {status_code}"
        if code in RATE_LIMIT_CODES or status_code == httpx.codes.TOO_MANY_REQUESTS:
            return ProviderRateLimited(label, provider=PROVIDER, retry_after=None)
        if code in TRANSIENT_CODES or status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            return ProviderUnavailable(label, provider=PROVIDER)
        return ProviderRejected(label, provider=PROVIDER)
