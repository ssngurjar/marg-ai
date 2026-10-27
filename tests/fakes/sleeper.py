"""A Sleeper that records waits and advances a FixedClock instead of sleeping."""

from datetime import timedelta

from tests.fakes.clock import FixedClock


class FakeSleeper:
    def __init__(self, clock: FixedClock) -> None:
        self.waits: list[float] = []
        self._clock = clock

    async def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self._clock.advance(timedelta(seconds=seconds))
