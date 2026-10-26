from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import SystemClock
from app.core.errors import (
    MargError,
    ProviderError,
    ProviderRateLimited,
    ProviderRejected,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
)
from tests.fakes.clock import FixedClock

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("error", "retryable"),
    [
        (ProviderTimeout("slow", provider="meta_model_api"), True),
        (ProviderUnavailable("503", provider="meta_model_api"), True),
        (ProviderRejected("400", provider="meta_model_api"), False),
        (ProviderResponseInvalid("bad json", provider="meta_model_api"), True),
        (ProviderResponseInvalid("truncated", provider="meta_model_api", retryable=False), False),
        (ProviderRateLimited("429", provider="meta_model_api", retry_after=None), True),
    ],
)
def test_provider_errors_fix_retryability(error: ProviderError, *, retryable: bool) -> None:
    assert error.retryable is retryable
    assert error.provider == "meta_model_api"
    assert isinstance(error, MargError)


def test_rate_limited_keeps_retry_after() -> None:
    assert ProviderRateLimited("429", provider="x", retry_after=2.5).retry_after == 2.5


def test_system_clock_returns_aware_utc() -> None:
    now = SystemClock().now()
    assert now.tzinfo is UTC


def test_fixed_clock_advances_only_when_told() -> None:
    clock = FixedClock(datetime(2026, 10, 27, tzinfo=UTC))
    clock.advance(timedelta(hours=6))
    assert clock.now() == datetime(2026, 10, 27, 6, tzinfo=UTC)


def test_fixed_clock_refuses_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FixedClock(datetime(2026, 10, 27))  # noqa: DTZ001  # the naive datetime is the point
