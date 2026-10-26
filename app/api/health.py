"""Liveness and readiness endpoints."""

import asyncio
from collections.abc import Sequence
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app.api.deps import get_environment, get_readiness_probes
from app.api.readiness import ProbeResult, ReadinessProbe, run_probe
from app.core.config import Environment

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    environment: Environment  # lets the s16 load driver refuse to run against prod
    checks: list[ProbeResult]


@router.get("/healthz")
async def healthz() -> HealthResponse:
    """Liveness: the process is serving. No I/O."""
    return HealthResponse(status="ok")


@router.get(
    "/readyz", responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}}
)
async def readyz(
    response: Response,
    probes: Annotated[Sequence[ReadinessProbe], Depends(get_readiness_probes)],
    environment: Annotated[Environment, Depends(get_environment)],
) -> ReadinessResponse:
    """Readiness: every critical dependency answers. Always returns the full list of checks."""
    results = list(await asyncio.gather(*(run_probe(probe) for probe in probes)))
    every_critical_probe_passed = all(result.ok for result in results if result.critical)
    if not every_critical_probe_passed:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if every_critical_probe_passed else "not_ready",
        environment=environment,
        checks=results,
    )
