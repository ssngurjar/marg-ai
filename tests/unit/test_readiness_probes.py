"""The s16 readiness probes: cached provider checks, the stalled queue, an HTTP health check."""

from datetime import timedelta

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.api.readiness import CachedCheck, ReadinessProbe, run_probe
from app.core.errors import ProviderUnavailable, StoreError
from app.providers.health.http_health_check import HealthEndpoint, HttpHealthCheck
from app.store.repositories.inbox_repository import InboxRepository
from app.wiring import QUEUE_STALL, queue_is_moving
from tests.fakes.clock import FixedClock
from tests.support.turn_context import NOW

pytestmark = pytest.mark.unit

URL = "https://api.example/v1/models"


class CountingCheck:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    async def __call__(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


async def test_a_cached_check_runs_once_per_minute() -> None:
    clock = FixedClock(NOW)
    check = CountingCheck()
    cached = CachedCheck(check, timedelta(seconds=60), clock)
    for _ in range(5):
        await cached()
    assert check.calls == 1
    clock.advance(timedelta(seconds=60))
    await cached()
    assert check.calls == 2


async def test_a_cached_failure_is_replayed_until_it_expires() -> None:
    clock = FixedClock(NOW)
    check = CountingCheck(ProviderUnavailable("down", provider="llama_guard"))
    cached = CachedCheck(check, timedelta(seconds=60), clock)
    for _ in range(3):
        with pytest.raises(ProviderUnavailable, match="down"):
            await cached()
    assert check.calls == 1
    check.error = None
    clock.advance(timedelta(seconds=61))
    await cached()  # recovered once the cache expired
    assert check.calls == 2


class WaitingInbox(InboxRepository):
    def __init__(self, waited: timedelta | None) -> None:  # no database
        self.waited = waited

    async def oldest_due_wait(self) -> timedelta | None:
        return self.waited


@pytest.mark.parametrize("waited", [None, timedelta(0), QUEUE_STALL])
async def test_a_moving_queue_is_ready(waited: timedelta | None) -> None:
    await queue_is_moving(WaitingInbox(waited))


async def test_a_message_waiting_over_a_minute_means_the_worker_is_stuck() -> None:
    with pytest.raises(StoreError, match="oldest message waiting 61 s"):
        await queue_is_moving(WaitingInbox(QUEUE_STALL + timedelta(seconds=1)))


def health(url: str = URL) -> HttpHealthCheck:
    return HttpHealthCheck(
        HealthEndpoint(provider="meta_model_api", url=url, token=SecretStr("k"), timeout_s=1)
    )


@respx.mock
async def test_a_200_is_healthy_and_the_token_is_sent() -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"data": []}))
    check = health()
    await check.check()
    assert route.calls.last.request.headers["authorization"] == "Bearer k"
    await check.aclose()


@pytest.mark.parametrize("status", [401, 429, 500, 503])
@respx.mock
async def test_any_other_status_is_unavailable_and_names_only_the_provider(status: int) -> None:
    respx.get(URL).mock(return_value=httpx.Response(status, text="secret body"))
    check = health()
    with pytest.raises(
        ProviderUnavailable, match=f"meta_model_api health: http {status}"
    ) as raised:
        await check.check()
    assert "secret body" not in str(raised.value)
    assert URL not in str(raised.value)
    await check.aclose()


@respx.mock
async def test_a_connection_failure_is_unavailable() -> None:
    respx.get(URL).mock(side_effect=httpx.ConnectError("refused"))
    check = health()
    with pytest.raises(ProviderUnavailable, match="ConnectError"):
        await check.check()
    await check.aclose()


async def test_a_failing_probe_reports_without_raising() -> None:
    probe = ReadinessProbe(
        name="safety",
        critical=True,
        check=CountingCheck(ProviderUnavailable("safety host flags a greeting", provider="x")),
    )
    result = await run_probe(probe)
    assert (result.ok, result.critical, result.detail) == (
        False, True, "safety host flags a greeting",
    )  # fmt: skip
