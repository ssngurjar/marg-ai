"""TeacherIntentReader: whether a teacher's free text asks for the three-field bridge or for
teaching help, and which chapter it names (owner, 2026-11-01). Read by Muse Spark; code acts on
it. If the call fails, the caller makes the bridge, as before.
"""

from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import ProviderError
from app.domain.enums import TeacherIntent
from app.domain.models.usage import StepUsage
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel


class TeacherIntentReading(BaseModel):
    """The model's reading (strict schema)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: TeacherIntent
    topic: str | None = Field(max_length=80)  # the chapter or topic the message names, if any


TEACHER_INTENT: Final = PromptSpec(prompt_id="teacher_intent", output_type=TeacherIntentReading)


@dataclass(frozen=True, slots=True)
class TeacherIntentRead:
    intent: TeacherIntent | None  # None: the call failed, the bridge path decides
    topic: str | None
    usage: StepUsage | None
    prompt_versions: dict[str, str]
    failed: str | None  # "teacher_intent_failed=<error>" when the call failed


class TeacherIntentReader:
    def __init__(self, llm: LanguageModel, registry: PromptRegistry) -> None:
        self._llm = llm
        self._registry = registry

    async def read(self, teacher_message: str, last_topic: str | None) -> TeacherIntentRead:
        rendered = self._registry.render(
            TEACHER_INTENT,
            system_vars={"last_topic": last_topic or "none"},
            user_vars={"teacher_message": teacher_message},
        )
        versions = {TEACHER_INTENT.prompt_id: rendered.request.prompt.prompt_version}
        try:
            result = await self._llm.generate(rendered.request)
        except ProviderError as exc:
            failed = f"teacher_intent_failed={type(exc).__name__}"
            return TeacherIntentRead(None, None, None, versions, failed)
        reading = result.output
        return TeacherIntentRead(reading.intent, reading.topic, result.usage, versions, None)
