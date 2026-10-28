"""Readiness probes: what `/readyz` checks, and how one check is run."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import BaseModel

from app.core.clock import Clock
from app.core.errors import MargError
from app.core.logging import get_logger

PROBE_TIMEOUT_S = 2.0

logger = get_logger(__name__)


class ProbeResult(BaseModel):
    name: str
    ok: bool
    detail: str | None  # e.g. "timeout"; never secrets or URLs with credentials
    critical: bool  # a failing critical probe makes the service not ready


@dataclass(frozen=True, slots=True)
class ReadinessProbe:
    """One dependency check. `check` raises a MargError when the dependency isn't usable."""

    name: str
    critical: bool
    check: Callable[[], Awaitable[None]]


async def run_probe(probe: ReadinessProbe) -> ProbeResult:
    """Run one probe with a time limit. A failure becomes ok=False; it never propagates."""
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_S):
            await probe.check()
    except TimeoutError:
        logger.warning("readiness_probe_failed", probe=probe.name, reason="timeout")
        return ProbeResult(name=probe.name, ok=False, detail="timeout", critical=probe.critical)
    except MargError as exc:
        logger.warning("readiness_probe_failed", probe=probe.name, reason=type(exc).__name__)
        return ProbeResult(name=probe.name, ok=False, detail=str(exc), critical=probe.critical)
    return ProbeResult(name=probe.name, ok=True, detail=None, critical=probe.critical)


class CachedCheck:
    """A provider check run at most once per `ttl`: `/readyz` is polled every few seconds, and
    a paid call (the safety classifier) or a rate-limited API must not be hit each time. The
    last outcome, success or the error, is replayed until it expires."""

    def __init__(self, check: Callable[[], Awaitable[None]], ttl: timedelta, clock: Clock) -> None:
        self._check = check
        self._ttl = ttl
        self._clock = clock
        self._checked_at: datetime | None = None
        self._error: MargError | None = None

    async def __call__(self) -> None:
        now = self._clock.now()
        if self._checked_at is None or now - self._checked_at >= self._ttl:
            try:
                await self._check()
                self._error = None
            except MargError as exc:
                self._error = exc
            self._checked_at = now
        if self._error is not None:
            raise self._error
