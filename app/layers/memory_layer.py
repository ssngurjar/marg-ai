"""MemoryLayer: a student's rolling memory, refreshed after each mentor or roadmap turn (s12 §4.7).

The model keeps what's still true, adds what's new and drops what the student contradicted.
A privacy check refuses anything that looks like a phone number, an ID or an email (one repair
retry, then the update is skipped). Runs as a post-turn task: it never touches the reply.
"""

import re
from typing import ClassVar, Final

from app.domain.models.student import MemoryUpdate, ProfileMemory
from app.domain.models.usage import StepUsage
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel

MEMORY: Final = PromptSpec(prompt_id="memory", output_type=MemoryUpdate)


class MemoryLayer:
    LONG_DIGITS: ClassVar[re.Pattern[str]] = re.compile(r"\d{6,}")
    EMAIL: ClassVar[re.Pattern[str]] = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")

    def __init__(self, llm: LanguageModel, registry: PromptRegistry) -> None:
        self._llm = llm
        self._registry = registry

    async def update(
        self, previous: ProfileMemory | None, user_text: str, reply_text: str
    ) -> tuple[MemoryUpdate, StepUsage, str]:
        """The new memory, its usage and the prompt version. Raises ProviderError (including
        when the output still fails the privacy check after the repair retry)."""
        rendered = self._registry.render(
            MEMORY,
            system_vars={},
            user_vars={
                "previous_memory": MemoryLayer._previous(previous),
                "student": user_text,
                "marg": reply_text,
            },
            semantic_check=MemoryLayer.privacy_problems,
        )
        result = await self._llm.generate(rendered.request)
        return result.output, result.usage, rendered.request.prompt.prompt_version

    @staticmethod
    def privacy_problems(update: MemoryUpdate) -> list[str]:
        texts = [update.summary, *update.ambitions, *update.constraints]
        problems: list[str] = []
        if any(MemoryLayer.LONG_DIGITS.search(text) for text in texts):
            problems.append("memory: remove every run of 6 or more digits")
        if any(MemoryLayer.EMAIL.search(text) for text in texts):
            problems.append("memory: remove every email address")
        return problems

    @staticmethod
    def _previous(previous: ProfileMemory | None) -> str:
        if previous is None:
            return "(none yet)"
        return (
            f"{previous.summary}\nAmbitions: {'; '.join(previous.ambitions) or '-'}\n"
            f"Constraints: {'; '.join(previous.constraints) or '-'}"
        )
