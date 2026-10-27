"""WebDemoIngestor: a web visitor's message into the same inbox as WhatsApp's (s14 §4.2-§4.7).

Thin by design, like the webhook: identify the visitor by their signed cookie, refuse what the
demo shouldn't take (a foreign origin, a rate limit, today's budget), validate the message once,
store a voice note, insert into the inbox and wake the visitor's turn. All model calls happen in
the worker, through the one pipeline.
"""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import ClassVar, Final, assert_never
from uuid import uuid4

from app.api.turn_waker import TurnWaker
from app.channels.web.web_message_parser import (
    WebButton,
    WebMessage,
    WebMessageParser,
    WebText,
    WebUpload,
    WebVoice,
)
from app.core.clock import Clock
from app.core.errors import DemoRefused
from app.core.signed_token_codec import SignedTokenCodec
from app.core.user_identity import UserIdentity
from app.domain.enums import Channel, MessageKind
from app.domain.models.base import UserHash
from app.domain.models.message import AudioClip, InboundMessage, MediaRef
from app.domain.rules.nudge_schedule import NudgeSchedule
from app.store.repositories.demo_repository import DemoRepository, MessageView, RateLimit
from app.store.repositories.inbox_repository import InboundRecord, InboxRepository
from app.store.repositories.media_blob_repository import MediaBlobRepository

SESSION_TTL: Final = timedelta(days=30)
COST_CACHE: Final = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class DemoLimits:
    per_session_per_hour: int  # DEMO_RATE_LIMIT_PER_HOUR
    per_ip_per_hour: int  # DEMO_IP_RATE_LIMIT_PER_HOUR
    sessions_per_ip_per_hour: int  # DEMO_SESSIONS_PER_IP_PER_HOUR
    max_audio_bytes: int  # DEMO_MAX_AUDIO_BYTES
    daily_cost_cap_usd: Decimal  # DAILY_COST_CAP_USD


@dataclass(frozen=True, slots=True)
class Visitor:
    user_hash: UserHash
    cookie: str | None  # a new or refreshed cookie to set, if any


@dataclass(frozen=True, slots=True)
class DemoDeps:
    identity: UserIdentity
    codec: SignedTokenCodec
    demo: DemoRepository
    media: MediaBlobRepository
    inbox: InboxRepository
    waker: TurnWaker
    clock: Clock


class WebDemoIngestor:
    PURPOSE: ClassVar[str] = "demo_session"

    def __init__(self, deps: DemoDeps, limits: DemoLimits) -> None:
        self._deps = deps
        self._limits = limits
        self._cost_checked_at: datetime | None = None
        self._cost_today = Decimal(0)

    async def visitor(self, cookie: str | None, client_ip: str) -> Visitor:
        """The visitor behind the cookie, or a new one (new sessions are limited per IP)."""
        now = self._deps.clock.now()
        verified = self._deps.codec.verify(cookie, "demo_session", now) if cookie else None
        if verified is not None and "sid" in verified.payload:
            sid = verified.payload["sid"]
            refreshed = self._issue(sid, now) if verified.needs_refresh else None
            return Visitor(UserHash(self._deps.identity.user_hash(Channel.WEB, sid)), refreshed)
        await self._check_limits(
            [
                RateLimit(
                    f"demo:session-create:{self._ip_key(client_ip)}",
                    self._limits.sessions_per_ip_per_hour,
                    "ip",
                )
            ],
            now,
        )
        sid = secrets.token_urlsafe(16)
        user_hash = UserHash(self._deps.identity.user_hash(Channel.WEB, sid))
        await self._deps.inbox.ensure_web_user(user_hash)
        return Visitor(user_hash, self._issue(sid, now))

    def known_visitor(self, cookie: str | None) -> UserHash:
        """For reads and uploads: a valid cookie, or DemoRefused("no_session")."""
        now = self._deps.clock.now()
        verified = self._deps.codec.verify(cookie, "demo_session", now) if cookie else None
        if verified is None or "sid" not in verified.payload:
            raise DemoRefused("no_session")
        return UserHash(self._deps.identity.user_hash(Channel.WEB, verified.payload["sid"]))

    async def submit(self, user_hash: UserHash, client_ip: str, upload: WebUpload) -> str:
        """Validate, store and enqueue one message. Returns its message id. Raises DemoRefused
        or WebInputInvalid; nothing is stored when either is raised."""
        now = self._deps.clock.now()
        await self._check_limits(
            [
                RateLimit(
                    f"demo:session:{user_hash}", self._limits.per_session_per_hour, "session"
                ),
                RateLimit(f"demo:ip:{self._ip_key(client_ip)}", self._limits.per_ip_per_hour, "ip"),
            ],
            now,
        )
        await self._check_budget(now)
        offered = await self._deps.demo.offered_buttons(user_hash) if upload.button_id else set()
        message = WebMessageParser.parse(upload, self._limits.max_audio_bytes, offered)
        await self._deps.inbox.ensure_web_user(user_hash)  # e.g. a cookie that outlived a reset
        inbound = await self._inbound(user_hash, message, now)
        await self._deps.inbox.save(
            [InboundRecord(message=inbound, address_ciphertext=None, raw_payload=None)]
        )
        self._deps.waker.wake(user_hash)
        return inbound.external_id

    async def _inbound(
        self, user_hash: UserHash, message: WebMessage, now: datetime
    ) -> InboundMessage:
        text: str | None = None
        media: MediaRef | None = None
        button: str | None = None
        match message:
            case WebText():
                kind, text = MessageKind.TEXT, message.text
            case WebButton():
                kind, button = MessageKind.INTERACTIVE, message.button_id
            case WebVoice():
                kind = MessageKind.AUDIO
                blob_id = await self._deps.media.save_inbound_audio(
                    user_hash,
                    AudioClip(data=message.data, mime_type=message.mime_type, duration_ms=None),
                )
                media = MediaRef(
                    channel=Channel.WEB,
                    provider_media_id=None,
                    blob_id=blob_id,
                    mime_type=message.mime_type,
                )
            case _:
                assert_never(message)
        return InboundMessage(
            channel=Channel.WEB,
            external_id=str(uuid4()),
            user_hash=user_hash,
            kind=kind,
            text=text,
            media=media,
            interactive_reply_id=button,
            provider_sent_at=now,
            received_at=now,
        )

    async def _check_limits(self, limits: list[RateLimit], now: datetime) -> None:
        broken = await self._deps.demo.over_limit(limits)
        if broken is not None:
            next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            wait = max(int((next_hour - now).total_seconds()), 1)
            raise DemoRefused("rate_limited", scope=broken.scope, retry_after_s=wait)

    async def _check_budget(self, now: datetime) -> None:
        """Today's web spend (IST day), re-read at most every 30 s (s14 §4.7)."""
        if self._cost_checked_at is None or now - self._cost_checked_at >= COST_CACHE:
            self._cost_today = await self._deps.demo.web_cost_since(
                NudgeSchedule.start_of_india_day(now)
            )
            self._cost_checked_at = now
        if self._cost_today >= self._limits.daily_cost_cap_usd:
            tomorrow = NudgeSchedule.start_of_india_day(now) + timedelta(days=1)
            raise DemoRefused(
                "daily_budget_reached", retry_after_s=int((tomorrow - now).total_seconds())
            )

    async def message_view(self, user_hash: UserHash, message_id: str) -> MessageView | None:
        return await self._deps.demo.message_view(user_hash, message_id)

    def _issue(self, sid: str, now: datetime) -> str:
        return self._deps.codec.issue("demo_session", {"sid": sid}, now, SESSION_TTL)

    def _ip_key(self, client_ip: str) -> str:
        """The raw IP is never stored: only a keyed hash of it."""
        return self._deps.identity.user_hash(Channel.WEB, f"ip:{client_ip}")[:32]
