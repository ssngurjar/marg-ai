"""AboutMargLayer: a question about Marg itself (how it keeps people safe, what it keeps, who
sees it, how to use it without reading, whether to trust it) answered only from the reviewed
facts in `app/constants/marg_facts.py`, for parents, students and teachers alike (owner,
2026-11-01). Anything the facts don't cover gets an honest "I don't know", counted.
"""

from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field

from app.constants.marg_facts import MARG_FACTS
from app.domain.enums import Language, Role, StepOutcome
from app.domain.models.reply import CanonicalReply
from app.domain.models.turn import TurnContext
from app.domain.rules.register_detector import RegisterDetector
from app.layers.layer_result import LayerResult
from app.layers.parent_question_layer import ParentQuestionLayer
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel


class AboutMargAnswer(BaseModel):
    """The model's structured reply (strict schema)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: str = Field(min_length=1, max_length=500)
    unknown: bool  # the facts don't answer it: said honestly, and counted
    spoken_text: str = Field(max_length=900)


ABOUT_MARG: Final = PromptSpec(prompt_id="about_marg", output_type=AboutMargAnswer)


class AboutMargLayer:
    LANGUAGE_RULES: ClassVar[dict[Language, str]] = {
        Language.HINDI: "Write answer in simple Hindi, in Devanagari script.",
        Language.HINGLISH: (
            "Write answer in Hinglish: Hindi in Roman script, the way people text on WhatsApp."
        ),
        Language.ENGLISH: "Write answer in simple, natural English.",
    }
    ROLE_NAMES: ClassVar[dict[Role, str]] = {
        Role.PARENT: "parent",
        Role.STUDENT: "student",
        Role.TEACHER: "teacher",
    }
    FACTS: ClassVar[str] = "\n".join(f"- {fact.topic}: {fact.text}" for fact in MARG_FACTS)

    def __init__(self, llm: LanguageModel, registry: PromptRegistry) -> None:
        self._llm = llm
        self._registry = registry

    async def answer(self, ctx: TurnContext, user_text: str, register: Language) -> LayerResult:
        """Raises a ProviderError when the model can't produce a valid reply."""
        role = ctx.profile.role
        rendered = self._registry.render(
            ABOUT_MARG,
            system_vars={
                "role": self.ROLE_NAMES[role] if role is not None else "person",
                "facts": self.FACTS,
                "language_rule": self.LANGUAGE_RULES[register],
                "spoken_rule": ParentQuestionLayer.SPOKEN_RULES[register],
            },
            user_vars={"question": user_text},
            semantic_check=lambda answer: self.script_problems(answer, register),
        )
        result = await self._llm.generate(rendered.request)
        reply = result.output
        degraded = bool(rendered.truncated_slots)
        return LayerResult(
            reply=CanonicalReply(
                body=reply.answer,
                body_language=register,
                spoken_text=reply.spoken_text,
                citations=[],
                buttons=[],
                fixed_kind=None,
            ),
            usages=[result.usage],
            prompt_versions={
                rendered.request.prompt.prompt_id: rendered.request.prompt.prompt_version
            },
            outcome=StepOutcome.DEGRADED if degraded else StepOutcome.OK,
            degraded_reason="truncated=true" if degraded else None,
            step_note="about_marg=unknown" if reply.unknown else "about_marg=true",
        )

    @staticmethod
    def script_problems(answer: AboutMargAnswer, register: Language) -> list[str]:
        """The repair turn's problems: is each field in the right script?"""
        problems: list[str] = []
        for problem in RegisterDetector.script_problems(
            answer.answer, answer.spoken_text, register
        ):
            if problem.startswith("text:"):
                problems.append("answer:" + problem.removeprefix("text:"))
            else:
                problems.append(problem)
        return problems
