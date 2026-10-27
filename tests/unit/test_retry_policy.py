"""RetryPolicy (contracts §5, s05 §4.2): what's retried, how long it waits, and the deadline."""

import random
from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import (
    ProviderError,
    ProviderRateLimited,
    ProviderRejected,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.providers.http import RetryPolicy, RetryTiming
from tests.fakes.clock import FixedClock
from tests.fakes.sleeper import FakeSleeper

pytestmark = pytest.mark.unit

T0 = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
PROVIDER = "whatsapp"


class Flaky:
    """Fails with the given errors in order, then returns "ok"."""

    def __init__(self, *errors: ProviderError) -> None:
        self.errors = list(errors)
        self.calls = 0

    async def __call__(self) -> str:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


def make_policy(attempts: int = 3) -> tuple[RetryPolicy, FakeSleeper, FixedClock]:
    clock = FixedClock(T0)
    sleeper = FakeSleeper(clock)
    policy = RetryPolicy(
        timing=RetryTiming(attempts=attempts), clock=clock, sleeper=sleeper, rng=seeded_rng()
    )
    return policy, sleeper, clock


DEADLINE = T0 + timedelta(seconds=30)


def seeded_rng() -> random.Random:
    return random.Random(7)  # noqa: S311  # deterministic jitter for tests, not cryptography


async def test_success_needs_one_call() -> None:
    policy, sleeper, _ = make_policy()
    operation = Flaky()
    assert await policy.run(operation, deadline=DEADLINE) == "ok"
    assert operation.calls == 1
    assert sleeper.waits == []


@pytest.mark.parametrize(
    "error",
    [
        ProviderTimeout("graph api messages timed out", provider=PROVIDER),
        ProviderUnavailable("graph api http 503", provider=PROVIDER),
        ProviderRateLimited("graph api error 130429", provider=PROVIDER, retry_after=None),
    ],
)
async def test_retryable_errors_are_retried_with_capped_jitter(error: ProviderError) -> None:
    policy, sleeper, _ = make_policy()
    operation = Flaky(error, error)
    assert await policy.run(operation, deadline=DEADLINE) == "ok"
    assert operation.calls == 3
    assert len(sleeper.waits) == 2
    assert 0 <= sleeper.waits[0] <= 0.5
    assert 0 <= sleeper.waits[1] <= 1.0


async def test_rejected_is_never_retried() -> None:
    policy, sleeper, _ = make_policy()
    operation = Flaky(ProviderRejected("graph api error 131047", provider=PROVIDER))
    with pytest.raises(ProviderRejected, match="131047"):
        await policy.run(operation, deadline=DEADLINE)
    assert operation.calls == 1
    assert sleeper.waits == []


async def test_an_invalid_response_is_retried_only_once() -> None:
    policy, _, _ = make_policy(attempts=5)
    invalid = ProviderResponseInvalid("unexpected GraphSendResponse", provider=PROVIDER)
    operation = Flaky(invalid, invalid, invalid)
    with pytest.raises(ProviderResponseInvalid, match="GraphSendResponse"):
        await policy.run(operation, deadline=DEADLINE)
    assert operation.calls == 2


async def test_retry_after_is_honoured() -> None:
    policy, sleeper, _ = make_policy()
    limited = ProviderRateLimited("graph api error 131056", provider=PROVIDER, retry_after=2.5)
    assert await policy.run(Flaky(limited), deadline=DEADLINE) == "ok"
    assert sleeper.waits == [2.5]


async def test_no_retry_that_would_pass_the_deadline() -> None:
    policy, sleeper, _ = make_policy()
    limited = ProviderRateLimited("graph api error 4", provider=PROVIDER, retry_after=10.0)
    operation = Flaky(limited)
    with pytest.raises(ProviderRateLimited, match="error 4"):
        await policy.run(operation, deadline=T0 + timedelta(seconds=5))
    assert operation.calls == 1
    assert sleeper.waits == []


async def test_the_last_error_is_raised_when_attempts_run_out() -> None:
    policy, _, _ = make_policy(attempts=2)
    first = ProviderUnavailable("graph api http 502", provider=PROVIDER)
    last = ProviderTimeout("graph api messages timed out", provider=PROVIDER)
    with pytest.raises(ProviderTimeout, match="timed out"):
        await policy.run(Flaky(first, last), deadline=DEADLINE)


@pytest.mark.parametrize("attempts", [0, -1])
def test_attempts_below_one_are_rejected(attempts: int) -> None:
    clock = FixedClock(T0)
    with pytest.raises(ValueError, match="attempts must be at least 1"):
        RetryPolicy(
            timing=RetryTiming(attempts=attempts),
            clock=clock,
            sleeper=FakeSleeper(clock),
            rng=seeded_rng(),
        )
