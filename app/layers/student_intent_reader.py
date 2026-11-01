"""StudentIntentReader: whether a student's free text asks for a plan, read by Muse Spark.

The router's plan words ("plan banao", "roadmap") are its fast path; a message they don't catch
("Mujhe IAS ka step by step rasta batao") went to the mentor (owner, 2026-11-01). Code routes on
the reading. If the call fails, the caller keeps the router's choice.
"""

from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ConfigDict

from app.core.errors import ProviderError
from app.domain.enums import StudentIntent
from app.domain.models.usage import StepUsage
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel


class StudentIntentReading(BaseModel):
    """The model's reading (strict schema)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: StudentIntent


STUDENT_INTENT: Final = PromptSpec(prompt_id="student_intent", output_type=StudentIntentReading)


@dataclass(frozen=True, slots=True)
class StudentIntentRead:
    intent: StudentIntent | None  # None: the call failed, the router's choice stands
    usage: StepUsage | None
    prompt_versions: dict[str, str]
    failed: str | None  # "student_intent_failed=<error>" when the call failed


class StudentIntentReader:
    def __init__(self, llm: LanguageModel, registry: PromptRegistry) -> None:
        self._llm = llm
        self._registry = registry

    async def read(self, student_message: str) -> StudentIntentRead:
        rendered = self._registry.render(
            STUDENT_INTENT, system_vars={}, user_vars={"student_message": student_message}
        )
        versions = {STUDENT_INTENT.prompt_id: rendered.request.prompt.prompt_version}
        try:
            result = await self._llm.generate(rendered.request)
        except ProviderError as exc:
            return StudentIntentRead(
                None, None, versions, f"student_intent_failed={type(exc).__name__}"
            )
        return StudentIntentRead(result.output.intent, result.usage, versions, None)
