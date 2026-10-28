"""CuriosityMomentLayer: the child's own question, answered through the parent (s10b §4.15, C11).

When a parent passes on the child's question ("Munni poochh rahi hai, chaand roz shape kyun
badalta hai?"), the reply is a true, simple answer to say to the child, a 2-minute way to find
out together with things at home, and one question back. If the model isn't confident of a true
answer, the reply says so honestly ("let's find out together") and keeps the mini-activity.
The supervision line is added by code. d7: the answer may talk about a hazard the child asked
about ("saanp ke kaan kahan hote hain?"), never the mini-activity, and never medicine (owner,
2026-10-28: talk about, never do). An answer that fails its checks twice is replaced by a fixed
serve-and-return reply, DEGRADED, never by an unchecked one.
"""

from dataclasses import dataclass
from datetime import date
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from app.constants.child_hazards import CHILD_HAZARD_WORDS, NEVER_TALK_ABOUT
from app.constants.journey_copy import (
    ASK_BACK_LABEL,
    CURIOSITY_FALLBACK,
    FIND_OUT_LABEL,
    LETS_FIND_OUT,
    SUPERVISION_LINE,
)
from app.constants.journey_words import CAREER_WORDS, EXPOSURE_PUSH_WORDS, LABEL_WORDS
from app.core.errors import ProviderResponseInvalid
from app.domain.enums import Language, StepOutcome
from app.domain.models.learner import Learner
from app.domain.models.reply import CanonicalReply
from app.domain.models.usage import StepUsage
from app.domain.rules.activity_validator import ActivityValidator
from app.domain.rules.child_hazard_matcher import ChildHazardMatcher
from app.domain.rules.phrase_finder import PhraseFinder
from app.domain.rules.register_detector import RegisterDetector
from app.domain.rules.stage_rules import StageRules
from app.layers.layer_result import LayerResult
from app.layers.parent_question_layer import ParentQuestionLayer
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel


class CuriosityMoment(BaseModel):
    """The model's answer (strict schema: every field required; empty when not a child's
    question)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_child_question: bool
    confident: bool
    say_to_child: str = Field(max_length=300)
    find_out_together: list[str] = Field(max_length=4)
    materials_used: list[str] = Field(max_length=6)
    ask_back: str = Field(max_length=160)
    who_explores_this: str = Field(max_length=160)
    spoken_text: str = Field(max_length=1200)


CURIOSITY_MOMENT: Final = PromptSpec(prompt_id="curiosity_moment", output_type=CuriosityMoment)
STEP_MAX_CHARS: Final = 160
UNKNOWN_AGE: Final = "3 to 8"  # several children and none chosen: the journey's age range


@dataclass(frozen=True, slots=True)
class NotAChildQuestion:
    """The model says the parent is asking for themselves: answer as a parent question, and
    keep this call's cost and prompt version on the turn."""

    usage: StepUsage
    prompt_versions: dict[str, str]


class CuriosityMomentLayer:
    def __init__(
        self, llm: LanguageModel, registry: PromptRegistry, materials: frozenset[str]
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._materials = materials

    async def answer(
        self,
        learner: Learner | None,
        parent_message: str,
        register: Language,
        today: date,
        *,
        voice: str,
    ) -> LayerResult | NotAChildQuestion:
        """The curiosity-moment reply, or NotAChildQuestion when the model says this isn't the
        child's own question. Raises ProviderError when the model can't be reached."""
        child_age = str(StageRules.age_on(learner.birth_year, today)) if learner else UNKNOWN_AGE
        asked = ChildHazardMatcher.asked_about(parent_message, CHILD_HAZARD_WORDS, NEVER_TALK_ABOUT)
        rendered = self._registry.render(
            CURIOSITY_MOMENT,
            system_vars={
                "language_rule": ParentQuestionLayer.LANGUAGE_RULES[register].replace(
                    "answer and try_this", "say_to_child, find_out_together and ask_back"
                )
                + f" {voice}",
                "spoken_rule": ParentQuestionLayer.SPOKEN_RULES[register],
                "child_age": child_age,
                "materials": ", ".join(sorted(self._materials)),
            },
            user_vars={
                "child": learner.nickname if learner and learner.nickname else "",
                "parent_message": parent_message,
            },
            semantic_check=lambda moment: _MomentChecks.problems(
                moment, self._materials, register, asked
            ),
        )
        versions = {rendered.request.prompt.prompt_id: rendered.request.prompt.prompt_version}
        try:
            result = await self._llm.generate(rendered.request)
        except ProviderResponseInvalid:
            return _fallback(register, versions)
        moment = result.output
        if not moment.is_child_question:
            return NotAChildQuestion(usage=result.usage, prompt_versions=versions)
        return LayerResult(
            reply=_MomentText.reply(moment, register),
            usages=[result.usage],
            prompt_versions=versions,
            outcome=StepOutcome.OK,
            degraded_reason=None,
            hazard_rule=asked,  # d7: only what the child asked about, and only talked about
        )


def _fallback(register: Language, versions: dict[str, str]) -> LayerResult:
    return LayerResult(
        reply=CanonicalReply(
            body=CURIOSITY_FALLBACK[register],
            body_language=register,
            spoken_text=CURIOSITY_FALLBACK[_spoken(register)],
            citations=[],
            buttons=[],
            fixed_kind=None,
        ),
        usages=[],
        prompt_versions=versions,
        outcome=StepOutcome.DEGRADED,
        degraded_reason="curiosity_fallback=ProviderResponseInvalid",
        hazard_rule=frozenset(),
    )


class _MomentText:
    @staticmethod
    def reply(moment: CuriosityMoment, register: Language) -> CanonicalReply:
        opening = moment.say_to_child if moment.confident else LETS_FIND_OUT[register]
        numbered = [
            f"{position}. {step}" for position, step in enumerate(moment.find_out_together, start=1)
        ]
        sections = [
            opening,
            "\n".join([FIND_OUT_LABEL[register], *numbered]),
            f"{ASK_BACK_LABEL[register]} {moment.ask_back}",
            *([moment.who_explores_this] if moment.who_explores_this.strip() else []),
            SUPERVISION_LINE[register],  # added by code, so a model can never drop it
        ]
        spoken_opening = "" if moment.confident else f"{LETS_FIND_OUT[_spoken(register)]} "
        return CanonicalReply(
            body="\n\n".join(sections),
            body_language=register,
            spoken_text=(
                f"{spoken_opening}{moment.spoken_text} {SUPERVISION_LINE[_spoken(register)]}"
            ),
            citations=[],
            buttons=[],
            fixed_kind=None,
        )


def _spoken(register: Language) -> Language:
    """Hinglish is spoken in Devanagari, so fixed lines in spoken text come from the Hindi."""
    return Language.HINDI if register is Language.HINGLISH else register


class _MomentChecks:
    """The semantic check (s10b §4.15): fixed-vocabulary problems for the one repair retry."""

    @staticmethod
    def problems(
        moment: CuriosityMoment,
        materials: frozenset[str],
        register: Language,
        asked: frozenset[str] = frozenset(),
    ) -> list[str]:
        if not moment.is_child_question:
            return []
        problems = _MomentChecks._required(moment)
        written = [
            moment.say_to_child,
            *moment.find_out_together,
            moment.ask_back,
            moment.who_explores_this,
        ]
        joined = " ".join(written)
        activity = " ".join(moment.find_out_together)
        if ChildHazardMatcher.undeclared(activity, CHILD_HAZARD_WORDS, ()):
            problems.append("find_out_together: nothing dangerous, even what the child asked about")
        if ChildHazardMatcher.undeclared(
            f"{joined} {moment.spoken_text}", CHILD_HAZARD_WORDS, asked
        ):
            problems.append("text: mentions a danger the child didn't ask about")
        if ActivityValidator.mentions_buying(written):
            problems.append("text: asks for something to be bought")
        unknown = sorted(set(moment.materials_used) - materials)
        if unknown:
            problems.append(f"materials_used: not in the list: {', '.join(unknown)}")
        if PhraseFinder.contains_any(joined, LABEL_WORDS):
            problems.append("text: labels the child")
        if PhraseFinder.contains_any(joined, CAREER_WORDS):
            problems.append("text: mentions careers, jobs or exams")
        if PhraseFinder.contains_any(moment.who_explores_this, EXPOSURE_PUSH_WORDS):
            problems.append("who_explores_this: tells the child to become something")
        problems.extend(RegisterDetector.script_problems(joined, moment.spoken_text, register))
        return problems

    @staticmethod
    def _required(moment: CuriosityMoment) -> list[str]:
        problems: list[str] = []
        if moment.confident and not moment.say_to_child.strip():
            problems.append("say_to_child: required when confident")
        if not moment.find_out_together:
            problems.append("find_out_together: give 1 to 4 steps")
        if any(not step.strip() or len(step) > STEP_MAX_CHARS for step in moment.find_out_together):
            problems.append(f"find_out_together: each step 1 to {STEP_MAX_CHARS} characters")
        if not moment.ask_back.strip():
            problems.append("ask_back: required")
        if not moment.spoken_text.strip():
            problems.append("spoken_text: required")
        return problems
