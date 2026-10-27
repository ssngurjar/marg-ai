"""SignedTokenCodec: small signed tokens for the demo cookie and dashboard links (contracts §3,
s14 §4.2). Standard library only.

    token = body "." signature
    body  = base64url(JSON {"v": 1, "payload": {...}, "iat": unix s, "exp": unix s})
    sig   = base64url(HMAC-SHA256(key, purpose + "." + body))

The purpose is part of what's signed, so a token issued for one use is never accepted for
another. A previous key is accepted for verification only, so the key can be rotated. Any
problem verifies as None: a bad cookie just means a new session, never an error to the visitor.
"""

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from app.core.logging import get_logger

type TokenPurpose = Literal["demo_session", "dash"]

logger = get_logger(__name__)


class _Body(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    v: Literal[1]
    payload: dict[str, str]
    iat: int
    exp: int


@dataclass(frozen=True, slots=True)
class VerifiedToken:
    payload: dict[str, str]
    needs_refresh: bool  # older than the refresh age, or signed with the previous key


class SignedTokenCodec:
    VERSION: ClassVar[Literal[1]] = 1
    CLOCK_SKEW: ClassVar[timedelta] = timedelta(minutes=5)
    REFRESH_AFTER: ClassVar[timedelta] = timedelta(days=7)

    def __init__(self, key: SecretStr, previous_key: SecretStr | None = None) -> None:
        self._key = key.get_secret_value().encode()
        self._previous = previous_key.get_secret_value().encode() if previous_key else None

    def issue(
        self, purpose: TokenPurpose, payload: dict[str, str], now: datetime, ttl: timedelta
    ) -> str:
        issued = int(now.timestamp())
        body = _Body(
            v=self.VERSION, payload=payload, iat=issued, exp=issued + int(ttl.total_seconds())
        )
        encoded = _b64(body.model_dump_json().encode())
        return f"{encoded}.{_b64(self._sign(self._key, purpose, encoded))}"

    def verify(self, token: str, purpose: TokenPurpose, now: datetime) -> VerifiedToken | None:
        encoded, separator, signature = token.rpartition(".")
        if not separator or not encoded:
            return None
        signed_with_previous = False
        if not self._matches(self._key, purpose, encoded, signature):
            if self._previous is None or not self._matches(
                self._previous, purpose, encoded, signature
            ):
                return None
            signed_with_previous = True
        body = _decode_body(encoded)
        if body is None:
            return None
        moment = int(now.timestamp())
        if body.iat > moment + self.CLOCK_SKEW.total_seconds() or body.exp <= moment:
            return None
        stale = moment - body.iat > self.REFRESH_AFTER.total_seconds()
        return VerifiedToken(payload=body.payload, needs_refresh=stale or signed_with_previous)

    def _matches(self, key: bytes, purpose: TokenPurpose, encoded: str, signature: str) -> bool:
        expected = _b64(self._sign(key, purpose, encoded))
        return hmac.compare_digest(expected.encode(), signature.encode())

    @staticmethod
    def _sign(key: bytes, purpose: TokenPurpose, encoded: str) -> bytes:
        return hmac.new(key, f"{purpose}.{encoded}".encode(), hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode_body(encoded: str) -> _Body | None:
    """The token's body, or None when it isn't valid base64url JSON of the right shape."""
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        return _Body.model_validate(json.loads(raw))
    except (binascii.Error, ValueError, ValidationError) as exc:
        # signed with our key but unreadable: a bug or an old format, never the visitor's fault
        logger.warning("signed_token_body_invalid", error=type(exc).__name__)
        return None
