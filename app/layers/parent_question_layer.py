"""ParentQuestionLayer: a parent's question answered warmly and practically (s10b §4.9, flow D).

The S5 exit layer (mvp-scope §6). S10b wraps it in JourneyLayer with the khoj flows (A, B, C, E).
It writes directly in the parent's register (C3c), so the translate step is skipped, and a
semantic check makes the model fix a reply in the wrong script (one repair retry, s05 §4.1).
"""

from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Language, StepOutcome
from app.domain.models.reply import CanonicalReply
from app.domain.models.turn import TurnContext
from app.domain.rules.register_detector import RegisterDetector
from app.layers.layer_result import LayerResult
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel


class ParentAnswer(BaseModel):
    """The model's structured reply (strict schema: every field required, no defaults)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: str = Field(min_length=1, max_length=500)
    try_this: str = Field(min_length=1, max_length=200)
    spoken_text: str = Field(min_length=1, max_length=900)


PARENT_ANSWER: Final = PromptSpec(prompt_id="parent_answer", output_type=ParentAnswer)


class ParentQuestionLayer:
    LANGUAGE_RULES: ClassVar[dict[Language, str]] = {
        Language.HINDI: "Write answer and try_this in simple Hindi, in Devanagari script.",
        Language.HINGLISH: (
            "Write answer and try_this in Hinglish: Hindi in Roman script, the way people "
            "text on WhatsApp."
        ),
        Language.ENGLISH: "Write answer and try_this in simple English.",
    }
    SPOKEN_RULES: ClassVar[dict[Language, str]] = {
        Language.HINDI: "Write spoken_text in Hindi, in Devanagari script.",
        Language.HINGLISH: "Write spoken_text in Hindi, in Devanagari script.",
        Language.ENGLISH: "Write spoken_text in English.",
    }
    DEVANAGARI_AT_LEAST: ClassVar[float] = 0.6  # Hindi text: Roman exam names are fine
    DEVANAGARI_AT_MOST: ClassVar[float] = 0.05  # Roman text: a stray Devanagari word is fine

    def __init__(self, llm: LanguageModel, registry: PromptRegistry) -> None:
        self._llm = llm
        self._registry = registry

    async def answer(self, ctx: TurnContext, user_text: str, register: Language) -> LayerResult:
        """Raises a ProviderError when the model can't produce a valid reply."""
        rendered = self._registry.render(
            PARENT_ANSWER,
            system_vars={
                "language_rule": self.LANGUAGE_RULES[register],
                "spoken_rule": self.SPOKEN_RULES[register],
            },
            user_vars={"parent_message": user_text},
            semantic_check=lambda answer: self.script_problems(answer, register),
        )
        result = await self._llm.generate(rendered.request)
        reply = result.output
        body = f"{reply.answer}\n\n{reply.try_this}"
        degraded = bool(rendered.truncated_slots)
        return LayerResult(
            reply=CanonicalReply(
                body=body,
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
        )

    @staticmethod
    def script_problems(answer: ParentAnswer, register: Language) -> list[str]:
        """Fixed-vocabulary problems for the repair turn: is each field in the right script?"""
        problems: list[str] = []
        written = f"{answer.answer} {answer.try_this}"
        written_share = RegisterDetector.devanagari_share(written) or 0.0
        spoken_share = RegisterDetector.devanagari_share(answer.spoken_text) or 0.0
        wants_devanagari_text = register is Language.HINDI
        wants_devanagari_speech = register in {Language.HINDI, Language.HINGLISH}
        if wants_devanagari_text and written_share < ParentQuestionLayer.DEVANAGARI_AT_LEAST:
            problems.append("answer, try_this: expected Devanagari script")
        if not wants_devanagari_text and written_share > ParentQuestionLayer.DEVANAGARI_AT_MOST:
            problems.append("answer, try_this: expected Roman script")
        if wants_devanagari_speech and spoken_share < ParentQuestionLayer.DEVANAGARI_AT_LEAST:
            problems.append("spoken_text: expected Devanagari script")
        if not wants_devanagari_speech and spoken_share > ParentQuestionLayer.DEVANAGARI_AT_MOST:
            problems.append("spoken_text: expected English in Roman script")
        return problems
