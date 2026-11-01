"""TeachingLayer: practical help to teach a chapter (owner, 2026-11-01): how to open the class
with something from village life, the idea in three simple steps, one question to check they
understood, and a mistake students often make. For a government school class of about 40, with
no projector, phone or anything to buy. The reply is assembled by code in the teacher's language,
and starts with the chapter, so a follow-up knows which one.
"""

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from app.constants.teacher_copy import (
    DEVICE_OR_PURCHASE_WORDS,
    EXPOSURE_BUTTONS,
    LABELS,
    MONEY_WORDS,
    TEACHING_LABELS,
)
from app.domain.enums import Language, StepOutcome
from app.domain.models.reply import CanonicalReply
from app.domain.models.turn import TurnContext
from app.domain.rules.phrase_finder import PhraseFinder
from app.domain.rules.register_detector import RegisterDetector
from app.layers.layer_result import LayerResult
from app.layers.local_voice import LocalVoice
from app.layers.mentor_layer import MentorLayer
from app.layers.parent_question_layer import ParentQuestionLayer
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel

THREE_STEPS: Final = 3


class TeachingAnswer(BaseModel):
    """The model's answer (strict schema)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    opening: str = Field(min_length=10, max_length=400)  # how to start the class
    steps: list[str] = Field(min_length=THREE_STEPS, max_length=THREE_STEPS)
    check_question: str = Field(min_length=5, max_length=200)
    common_mistake: str = Field(min_length=5, max_length=300)
    spoken_text: str = Field(max_length=1500)


TEACHING_ANSWER: Final = PromptSpec(prompt_id="teaching_answer", output_type=TeachingAnswer)


class TeachingLayer:
    def __init__(self, llm: LanguageModel, registry: PromptRegistry) -> None:
        self._llm = llm
        self._registry = registry

    async def answer(
        self, ctx: TurnContext, user_text: str, topic: str, register: Language
    ) -> LayerResult:
        """Raises ProviderError when the model can't give a valid answer."""
        profile = ctx.profile
        rendered = self._registry.render(
            TEACHING_ANSWER,
            system_vars={
                "topic": topic,
                "grade": str(profile.grade) if profile.grade else "not known",
                "subject": profile.subject or "not known",
                "district": profile.district or "not known",
                "language_rule": LocalVoice.language_rule(
                    ParentQuestionLayer.LANGUAGE_RULES[register].replace(
                        "answer and try_this", "every text field"
                    ),
                    register,
                    ctx,
                    user_text,
                ),
                "spoken_rule": ParentQuestionLayer.SPOKEN_RULES[register],
            },
            user_vars={"teacher_message": user_text},
            semantic_check=lambda answer: TeachingLayer.problems(answer, register),
        )
        result = await self._llm.generate(rendered.request)
        return LayerResult(
            reply=TeachingLayer.render(result.output, topic, register),
            usages=[result.usage],
            prompt_versions={TEACHING_ANSWER.prompt_id: rendered.request.prompt.prompt_version},
            outcome=StepOutcome.OK,
            degraded_reason=None,
            hazard_rule=None,
        )

    @staticmethod
    def problems(answer: TeachingAnswer, register: Language) -> list[str]:
        """As a bridge's activities (s10 §4.4): nothing to buy or plug in, no money figures."""
        texts = [answer.opening, *answer.steps, answer.check_question, answer.common_mistake]
        problems: list[str] = []
        if any(PhraseFinder.contains_any(text, DEVICE_OR_PURCHASE_WORDS) for text in texts):
            problems.append("text: no projector, phone, internet, printout or buying")
        if any(
            MentorLayer.FACT_FIGURE.search(text) or PhraseFinder.contains_any(text, MONEY_WORDS)
            for text in texts
        ):
            problems.append("text: no money amounts, percentages or years")
        problems.extend(
            RegisterDetector.script_problems(" ".join(texts), answer.spoken_text, register)
        )
        return problems

    @staticmethod
    def render(answer: TeachingAnswer, topic: str, register: Language) -> CanonicalReply:
        labels = TEACHING_LABELS[register]
        steps = "\n".join(f"{number}. {step}" for number, step in enumerate(answer.steps, start=1))
        sections = [
            f"{LABELS[register]['topic']}: {topic}",
            f"{labels['start']}: {answer.opening}",
            f"{labels['steps']}:\n{steps}",
            f"{labels['check']}: {answer.check_question}",
            f"{labels['mistake']}: {answer.common_mistake}",
        ]
        return CanonicalReply(
            body="\n\n".join(sections),
            body_language=register,
            spoken_text=answer.spoken_text,
            citations=[],
            buttons=list(EXPOSURE_BUTTONS[register]),
            fixed_kind=None,
        )
