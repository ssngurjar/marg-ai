"""ProviderBreaker: one provider's breaker, held for the life of the process (s07, owner
2026-11-01).

The rules are `CircuitBreaker`'s; this keeps the state, logs when the breaker opens and closes,
and runs the probe in the background, so the call that found the breaker open goes straight to
the backup and never waits for the probe.
"""

import asyncio
from collections.abc import Callable, Coroutine

from app.core.circuit_breaker import BreakerLimits, BreakerState, CircuitBreaker
from app.core.clock import Clock
from app.core.logging import get_logger

logger = get_logger(__name__)

Probe = Callable[[], Coroutine[None, None, bool]]  # True when the provider answered


class ProviderBreaker:
    def __init__(self, provider: str, limits: BreakerLimits, clock: Clock) -> None:
        self._provider = provider
        self._limits = limits
        self._clock = clock
        self._state = BreakerState()
        self._probe_task: asyncio.Task[bool] | None = None

    def is_open(self) -> bool:
        return CircuitBreaker.is_open(self._state, self._clock.now())

    def failed(self) -> None:
        was_open = self.is_open()
        self._state = CircuitBreaker.after_failure(self._state, self._limits, self._clock.now())
        if not was_open and self.is_open():
            logger.warning(
                "breaker_opened",
                provider=self._provider,
                skipped_for_s=self._limits.open_for.total_seconds(),
            )

    def succeeded(self) -> None:
        if self.is_open():
            logger.info("breaker_closed", provider=self._provider)
        self._state = CircuitBreaker.after_success()

    def probe_if_due(self, probe: Probe) -> None:
        """Start `probe` in the background when one is due and none is running."""
        now = self._clock.now()
        if self._probe_task is not None and not self._probe_task.done():
            return
        if not CircuitBreaker.probe_due(self._state, self._limits, now):
            return
        self._state = CircuitBreaker.probe_started(self._state, now)
        self._probe_task = asyncio.create_task(probe())
        self._probe_task.add_done_callback(self._probe_finished)

    async def aclose(self) -> None:
        if self._probe_task is not None and not self._probe_task.done():
            self._probe_task.cancel()
            await asyncio.gather(self._probe_task, return_exceptions=True)

    def _probe_finished(self, task: "asyncio.Task[bool]") -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            # A probe returns False for a provider failure; anything else is our bug.
            logger.error("breaker_probe_crashed", provider=self._provider, exc_info=error)
            return
        if task.result():
            self.succeeded()
