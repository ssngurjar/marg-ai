"""A SafetyClassifier that returns scripted categories or fails, and records what it was asked."""

import asyncio
from collections.abc import Callable
from decimal import Decimal
from typing import Literal

from app.core.errors import ProviderError
from app.domain.enums import SafetyCategory, SafetyDecision
from app.domain.models.safety import SafetyVerdict
from app.domain.models.usage import StepUsage
from app.providers.ports import SafetyRequest

type Speaker = Literal["user", "assistant"]

FREE_USAGE = StepUsage(
    provider="llama_guard",
    model="fake-guard",
    input_tokens=10,
    output_tokens=2,
    audio_seconds=None,
    cost_usd=Decimal("0"),
)
BOTH_SPEAKERS: frozenset[Speaker] = frozenset({"user", "assistant"})


class FakeSafetyClassifier:
    """Satisfies `SafetyClassifier`.

    `flag` decides the categories per request; `error` is raised for the speakers in `fail_on`;
    `delay_s` makes every call slow (to test timeouts).
    """

    def __init__(
        self,
        flag: Callable[[SafetyRequest], list[SafetyCategory]] | None = None,
        error: ProviderError | None = None,
        *,
        fail_on: frozenset[Speaker] = BOTH_SPEAKERS,
        delay_s: float = 0.0,
    ) -> None:
        self.requests: list[SafetyRequest] = []
        self._flag = flag
        self._error = error
        self._fail_on = fail_on
        self._delay_s = delay_s

    async def classify(self, request: SafetyRequest) -> tuple[SafetyVerdict, StepUsage]:
        self.requests.append(request)
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        if self._error is not None and request.speaker in self._fail_on:
            raise self._error
        categories = self._flag(request) if self._flag else []
        decision = SafetyDecision.BLOCK if categories else SafetyDecision.ALLOW
        return SafetyVerdict(
            decision=decision, categories=categories, source="llama_guard"
        ), FREE_USAGE

    def speakers(self) -> list[Speaker]:
        return [request.speaker for request in self.requests]
