"""AspirationSignalExtractor: where a student is heading, from their own words (s13 §4.3).

Runs after the reply is sent; its output is telemetry, never shown. Muse Spark Open (C9), with
Spark 1.3 as the fallback, like the curiosity extraction it continues.
"""

from dataclasses import dataclass
from typing import Final

from app.domain.models.aspiration import AspirationSignals, ExtractAspiration
from app.domain.models.usage import StepUsage
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel

ASPIRATION_EXTRACT: Final = PromptSpec(
    prompt_id="aspiration_extract", output_type=AspirationSignals
)


@dataclass(frozen=True, slots=True)
class ExtractedAspiration:
    signals: AspirationSignals
    usage: StepUsage
    prompt_version: str


class AspirationSignalExtractor:
    def __init__(self, llm: LanguageModel, registry: PromptRegistry) -> None:
        self._llm = llm
        self._registry = registry

    async def extract(self, task: ExtractAspiration) -> ExtractedAspiration:
        """Raises ProviderError when the model can't give valid signals."""
        rendered = self._registry.render(
            ASPIRATION_EXTRACT,
            system_vars={"grade": str(task.grade) if task.grade is not None else "unknown"},
            user_vars={"previous_exchange": task.previous_exchange, "student": task.user_text},
        )
        result = await self._llm.generate(rendered.request)
        return ExtractedAspiration(
            result.output, result.usage, rendered.request.prompt.prompt_version
        )
