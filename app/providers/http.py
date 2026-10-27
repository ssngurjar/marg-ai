"""The one retry policy every external call uses (contracts §5, s05 §4.2).

Deadline-aware, exponential backoff with full jitter, `Retry-After` honoured. No ad-hoc retry
loops anywhere else, and no tenacity: the policy has to know the step's deadline.
"""

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from app.core.clock import Clock
from app.core.errors import ProviderError, ProviderRateLimited, ProviderResponseInvalid


class Sleeper(Protocol):
    async def sleep(self, seconds: float) -> None: ...


class AsyncioSleeper:
    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


@dataclass(frozen=True, slots=True)
class RetryTiming:
    """contracts §5: 3 attempts (including the first), 0.5 s base doubling, capped at 4 s."""

    attempts: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 4.0


class RetryPolicy:
    def __init__(
        self, *, timing: RetryTiming, clock: Clock, sleeper: Sleeper, rng: random.Random
    ) -> None:
        if timing.attempts < 1:
            raise ValueError(f"attempts must be at least 1, got {timing.attempts}")
        self._attempts = timing.attempts
        self._base_delay_s = timing.base_delay_s
        self._max_delay_s = timing.max_delay_s
        self._clock = clock
        self._sleeper = sleeper
        self._rng = rng

    async def run[ResultT](
        self, operation: Callable[[], Awaitable[ResultT]], *, deadline: datetime
    ) -> ResultT:
        """Run `operation`, retrying retryable `ProviderError`s while attempts and time remain.

        `ProviderRejected` is never retried; `ProviderResponseInvalid` at most once. A retry is
        skipped if its wait would pass `deadline`. The last error is re-raised unchanged.
        """
        invalid_responses = 0
        for attempt in range(self._attempts):
            try:
                return await operation()
            except ProviderError as error:
                if isinstance(error, ProviderResponseInvalid):
                    invalid_responses += 1
                is_last = attempt == self._attempts - 1
                if is_last or not self._should_retry(error, invalid_responses):
                    raise
                delay_s = self._delay_s(error, attempt)
                if self._clock.now() + timedelta(seconds=delay_s) >= deadline:
                    raise
                await self._sleeper.sleep(delay_s)
        raise AssertionError("unreachable: the loop returns or raises on its last attempt")

    def _should_retry(self, error: ProviderError, invalid_responses: int) -> bool:
        if not error.retryable:
            return False
        return not (isinstance(error, ProviderResponseInvalid) and invalid_responses > 1)

    def _delay_s(self, error: ProviderError, attempt: int) -> float:
        if isinstance(error, ProviderRateLimited) and error.retry_after is not None:
            return error.retry_after
        ceiling = min(self._max_delay_s, self._base_delay_s * (1 << attempt))
        return self._rng.uniform(0, ceiling)
