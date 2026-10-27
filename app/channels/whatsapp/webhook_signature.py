"""WebhookSignatureVerifier: is this request really from Meta? (s03 §4.2, §4.3)."""

import hashlib
import hmac
import re
from typing import ClassVar

from pydantic import SecretStr

from app.core.errors import SignatureInvalid


class WebhookSignatureVerifier:
    SIGNATURE_PREFIX: ClassVar[str] = "sha256="
    _HEX_DIGEST: ClassVar[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}")

    @staticmethod
    def verify(raw_body: bytes, signature_header: str | None, app_secret: SecretStr) -> None:
        """Raise SignatureInvalid unless the header is a valid HMAC-SHA256 of the raw body.

        Must be given the raw request bytes: re-serialised JSON changes the bytes and the digest.
        """
        prefix = WebhookSignatureVerifier.SIGNATURE_PREFIX
        if signature_header is None:
            raise SignatureInvalid("X-Hub-Signature-256 header is missing")
        if not signature_header.startswith(prefix):
            raise SignatureInvalid("X-Hub-Signature-256 doesn't start with sha256=")
        received = signature_header.removeprefix(prefix).lower()
        if not WebhookSignatureVerifier._HEX_DIGEST.fullmatch(received):
            raise SignatureInvalid("X-Hub-Signature-256 isn't a 64-character hex digest")
        expected = hmac.new(
            app_secret.get_secret_value().encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(received, expected):
            raise SignatureInvalid("X-Hub-Signature-256 doesn't match the body")

    @staticmethod
    def verify_subscription(mode: str | None, token: str | None, expected: SecretStr) -> bool:
        """True only for Meta's subscribe handshake carrying our verify token (constant-time)."""
        if mode != "subscribe" or token is None:
            return False
        return hmac.compare_digest(token.encode(), expected.get_secret_value().encode())
