"""IntentReader: what a parent's free text means, read by Muse Spark into a fixed set.

Buttons, safety, consent and deletion stay deterministic (the router); this reads only a
parent's typed or spoken words while the journey waits, where word lists were always one
phrase behind real users ("Hi" taken as a khoj report; owner, 2026-10-29). Code acts on the
intent. If the call fails, the caller falls back to its rules.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ConfigDict

from app.core.errors import ProviderError
from app.domain.enums import Language, ParentIntent
from app.domain.models.learner import Learner
from app.domain.models.turn import Exchange
from app.domain.models.usage import StepUsage
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel

MARG_SAID_MAX_CHARS: Final = 400


class IntentReading(BaseModel):
    """The model's reading (strict schema)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: ParentIntent
    language: Language  # what the words are written in (hinglish: Hindi in Roman letters)
    braj: bool  # Braj forms (मेरो, वाको, वाय, नाय…), in either script
    asked_language: Language | None  # a language the parent asks this reply to be in, if any
    child_name: str | None  # child_name only: the home name the parent gives, as written


PARENT_INTENT: Final = PromptSpec(prompt_id="parent_intent", output_type=IntentReading)


@dataclass(frozen=True, slots=True)
class IntentRead:
    intent: ParentIntent | None  # None: the call failed, the caller's rules decide
    usage: StepUsage | None
    language: Language | None
    braj: bool
    asked_language: Language | None  # "send khoj in hindi": this reply's language (2026-11-01)
    child_name: str | None  # "bacche ka naam Prisa hai": the name given (2026-11-01)
    prompt_versions: dict[str, str]
    failed: str | None  # "intent_read_failed=<error>" when the call failed


class IntentReader:
    def __init__(self, llm: LanguageModel, registry: PromptRegistry) -> None:
        self._llm = llm
        self._registry = registry

    async def read(
        self,
        parent_message: str,
        open_khoj_title: str | None,
        learners: Sequence[Learner],
        recent: Sequence[Exchange],
    ) -> IntentRead:
        children = (
            ", ".join(learner.nickname or "a child" for learner in learners) or "none recorded"
        )
        marg_said = recent[-1].reply_text[:MARG_SAID_MAX_CHARS] if recent else ""
        rendered = self._registry.render(
            PARENT_INTENT,
            system_vars={"open_khoj": open_khoj_title or "none"},
            user_vars={
                "children": children,
                "marg_said": marg_said,
                "parent_message": parent_message,
            },
        )
        versions = {PARENT_INTENT.prompt_id: rendered.request.prompt.prompt_version}
        try:
            result = await self._llm.generate(rendered.request)
        except ProviderError as exc:
            failed = f"intent_read_failed={type(exc).__name__}"
            return IntentRead(
                None,
                None,
                None,
                braj=False,
                asked_language=None,
                child_name=None,
                prompt_versions=versions,
                failed=failed,
            )
        reading = result.output
        return IntentRead(
            reading.intent,
            result.usage,
            reading.language,
            braj=reading.braj,
            asked_language=reading.asked_language,
            child_name=reading.child_name,
            prompt_versions=versions,
            failed=None,
        )
