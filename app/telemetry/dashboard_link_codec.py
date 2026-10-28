"""DashboardLinkCodec: signed dashboard links and cookies (s13 §4.9, decision A4).

No passwords: `marg admin-link` mints a 15-minute admin link; opening it swaps the token for a
2-hour HttpOnly cookie. A teacher who sends "dashboard" gets a link to their own district's
students. Tokens are the shared SignedTokenCodec's, purpose "dash", so a web demo session can
never be read as a dashboard token. Any problem is LinkInvalid, never which check failed.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.clock import Clock
from app.core.errors import LinkInvalid
from app.core.signed_token_codec import SignedTokenCodec


class DashboardClaims(BaseModel):
    """`admin`: everything, at the admin floor. `teacher`: the students of one district only,
    at the normal floor (the teacher's user hash is `sub`; `district` as onboarding stored it)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    v: Literal["1"]
    scope: Literal["admin", "teacher"]
    sub: str = Field(min_length=1, max_length=64)
    district: str = Field(max_length=80)  # "" for admin

    @model_validator(mode="after")
    def _scoped(self) -> Self:
        if self.scope == "admin" and (self.sub != "admin" or self.district):
            raise ValueError("an admin token has sub admin and no district")
        if self.scope == "teacher" and (self.sub == "admin" or not self.district):
            raise ValueError("a teacher token names the teacher and a district")
        return self


ADMIN: DashboardClaims = DashboardClaims(v="1", scope="admin", sub="admin", district="")


def teacher_claims(user_hash: str, district: str) -> DashboardClaims:
    return DashboardClaims(v="1", scope="teacher", sub=user_hash, district=district)


@dataclass(frozen=True, slots=True)
class DashboardLinkSettings:
    link_ttl: timedelta  # DASHBOARD_LINK_TTL_S
    cookie_ttl: timedelta  # DASHBOARD_COOKIE_TTL_S


class DashboardLinkCodec:
    def __init__(
        self, codec: SignedTokenCodec, clock: Clock, settings: DashboardLinkSettings
    ) -> None:
        self._codec = codec
        self._clock = clock
        self._settings = settings

    def link_token(self, claims: DashboardClaims) -> str:
        return self._issue(claims, self._settings.link_ttl)

    def cookie_token(self, claims: DashboardClaims) -> str:
        return self._issue(claims, self._settings.cookie_ttl)

    @property
    def cookie_ttl(self) -> timedelta:
        return self._settings.cookie_ttl

    def read(self, token: str) -> DashboardClaims:
        """Raises LinkInvalid for a bad signature, an expired or wrong-purpose token, or claims
        this version doesn't know."""
        verified = self._codec.verify(token, "dash", self._clock.now())
        if verified is None:
            raise LinkInvalid("dashboard token rejected")
        try:
            return DashboardClaims.model_validate(verified.payload)
        except ValidationError as exc:
            raise LinkInvalid("dashboard token has unknown claims") from exc

    def _issue(self, claims: DashboardClaims, ttl: timedelta) -> str:
        return self._codec.issue("dash", claims.model_dump(), self._clock.now(), ttl)
