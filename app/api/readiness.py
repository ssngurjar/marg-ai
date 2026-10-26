"""Readiness probes: what `/readyz` checks, and how one check is run."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel

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
