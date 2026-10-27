"""A LanguageModel that returns scripted outputs (as JSON-like dicts) or raises scripted errors."""

import asyncio
from collections.abc import Mapping, Sequence
from decimal import Decimal

from pydantic import BaseModel

from app.core.errors import ProviderError
from app.domain.models.usage import StepUsage
from app.providers.ports import GenerationRequest, GenerationResult, RenderedPrompt

type ScriptedOutput = Mapping[str, object] | ProviderError

USAGE = StepUsage(
    provider="meta_model_api",
    model="muse-spark-1.3",
    input_tokens=300,
    output_tokens=200,
    audio_seconds=None,
    cost_usd=Decimal("0.001225"),
)


class FakeLanguageModel:
    """Satisfies `LanguageModel`. Each call takes the next scripted output (the last repeats)."""

    def __init__(self, outputs: Sequence[ScriptedOutput], delay_s: float = 0.0) -> None:
        self.outputs = list(outputs)
        self.prompts: list[RenderedPrompt] = []
        self.cancelled = False
        self._delay_s = delay_s

    async def generate[OutputT: BaseModel](
        self, request: GenerationRequest[OutputT]
    ) -> GenerationResult[OutputT]:
        self.prompts.append(request.prompt)
        try:
            if self._delay_s:
                await asyncio.sleep(self._delay_s)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        scripted = self.outputs[min(len(self.prompts) - 1, len(self.outputs) - 1)]
        if isinstance(scripted, ProviderError):
            raise scripted
        output = request.output_type.model_validate(scripted)
        if request.semantic_check is not None and request.semantic_check(output):
            raise AssertionError("scripted output fails the request's semantic check")
        return GenerationResult(output=output, usage=USAGE, latency_ms=5)
