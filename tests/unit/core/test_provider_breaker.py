"""ProviderBreaker: one provider's breaker held across calls, with its probe in the background
(s07, owner 2026-11-01)."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.core.circuit_breaker import BreakerLimits
from app.core.provider_breaker import ProviderBreaker
from tests.fakes.clock import FixedClock

pytestmark = pytest.mark.unit

START = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
LIMITS = BreakerLimits(
    failures_to_open=2,
    failure_window=timedelta(seconds=60),
    open_for=timedelta(minutes=5),
    probe_every=timedelta(seconds=30),
)


def opened() -> tuple[ProviderBreaker, FixedClock]:
    clock = FixedClock(START)
    breaker = ProviderBreaker("llama_guard", LIMITS, clock)
    breaker.failed()
    breaker.failed()
    return breaker, clock


class Probe:
    """A probe the test scripts: its answer, and how often it ran."""

    def __init__(self, *, answers: bool) -> None:
        self.answers = answers
        self.runs = 0
        self.release = asyncio.Event()
        self.release.set()

    async def __call__(self) -> bool:
        self.runs += 1
        await self.release.wait()
        return self.answers


async def settle() -> None:
    for _ in range(3):
        await asyncio.sleep(0)


async def test_two_failures_open_it_and_a_success_closes_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    breaker, _ = opened()
    assert breaker.is_open()
    breaker.succeeded()
    assert not breaker.is_open()
    logged = capsys.readouterr().out
    assert "breaker_opened" in logged
    assert "breaker_closed" in logged


async def test_no_probe_runs_before_half_a_minute() -> None:
    breaker, clock = opened()
    probe = Probe(answers=True)
    clock.advance(timedelta(seconds=29))
    breaker.probe_if_due(probe)
    await settle()
    assert probe.runs == 0
    assert breaker.is_open()


async def test_a_probe_that_gets_an_answer_closes_it() -> None:
    breaker, clock = opened()
    probe = Probe(answers=True)
    clock.advance(timedelta(seconds=30))
    breaker.probe_if_due(probe)
    await settle()
    assert probe.runs == 1
    assert not breaker.is_open()


async def test_a_probe_without_an_answer_keeps_it_open_and_the_next_waits() -> None:
    breaker, clock = opened()
    probe = Probe(answers=False)
    clock.advance(timedelta(seconds=30))
    breaker.probe_if_due(probe)
    await settle()
    breaker.probe_if_due(probe)
    await settle()
    assert probe.runs == 1
    assert breaker.is_open()
    clock.advance(timedelta(seconds=30))
    breaker.probe_if_due(probe)
    await settle()
    assert probe.runs == 2


async def test_only_one_probe_runs_at_a_time() -> None:
    breaker, clock = opened()
    slow = Probe(answers=True)
    slow.release.clear()
    clock.advance(timedelta(seconds=30))
    breaker.probe_if_due(slow)
    await settle()
    clock.advance(timedelta(seconds=30))
    breaker.probe_if_due(slow)
    await settle()
    assert slow.runs == 1
    slow.release.set()
    await settle()
    assert not breaker.is_open()


async def test_after_five_minutes_it_closes_on_its_own() -> None:
    breaker, clock = opened()
    clock.advance(timedelta(minutes=5))
    assert not breaker.is_open()


async def test_closing_cancels_a_running_probe() -> None:
    breaker, clock = opened()
    stuck = Probe(answers=True)
    stuck.release.clear()
    clock.advance(timedelta(seconds=30))
    breaker.probe_if_due(stuck)
    await settle()
    await breaker.aclose()
    assert breaker.is_open()  # the cancelled probe closed nothing


async def test_a_probe_that_crashes_is_logged_and_leaves_it_open(
    capsys: pytest.CaptureFixture[str],
) -> None:
    breaker, clock = opened()

    async def crashing() -> bool:
        raise RuntimeError("a bug in the probe")

    clock.advance(timedelta(seconds=30))
    breaker.probe_if_due(crashing)
    await settle()
    assert breaker.is_open()
    logged = capsys.readouterr().out
    assert "breaker_probe_crashed" in logged
    assert "a bug in the probe" in logged
