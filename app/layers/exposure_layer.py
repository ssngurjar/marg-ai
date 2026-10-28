"""ExposureLayer: a teacher's chapter connected to three real-world fields (s10, the Exposure
layer).

    exp:new, or exp:more with no earlier bridge → the fixed ask-for-chapter text, no model call
    anything else → the model chooses: bridge, clarify, or more_activity

A bridge has exactly three distinct fields, at least one outside science, each with a five-minute
activity needing no electricity, device or purchase. The checks refuse devices, purchases and
money in any field (one repair retry). The reply is assembled by code in the teacher's register
(C3c), most important first, since the voice note reads its start. An official NCERT chapter
title, when the catalogue recognises one, is a hint, never a gate.
"""

from collections.abc import Sequence
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.constants.teacher_copy import (
    ASK_CHAPTER,
    DEVICE_OR_PURCHASE_WORDS,
    EXPOSURE_BUTTONS,
    LABELS,
    MONEY_WORDS,
    MORE_ACTIVITY,
    NEW_CHAPTER,
)
from app.core.errors import DomainError
from app.domain.enums import Language, Role, Route, StepOutcome
from app.domain.models.reply import CanonicalReply
from app.domain.models.turn import Exchange, TurnContext
from app.domain.rules.chapter_matcher import ChapterMatcher
from app.domain.rules.phrase_finder import PhraseFinder
from app.domain.rules.register_detector import RegisterDetector
from app.layers.curriculum_catalogue import ChapterCatalogue
from app.layers.layer_result import LayerResult
from app.layers.mentor_layer import MentorLayer
from app.layers.parent_question_layer import ParentQuestionLayer
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel

type Career = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)]
type Material = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)
]


class ExposureField(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str = Field(min_length=2, max_length=60)
    field_kind: Literal["stem", "non_stem"]
    why_it_connects: str = Field(min_length=10, max_length=300)
    example_from_india: str = Field(min_length=10, max_length=300)
    five_minute_activity: str = Field(min_length=20, max_length=500)
    activity_materials: list[Material] = Field(max_length=6)
    needs_electricity: bool
    needs_purchase: bool
    careers: list[Career] = Field(min_length=2, max_length=4)
    local_hook: str = Field(min_length=5, max_length=200)


class ExposureBridge(BaseModel):
    """The model's answer (strict schema: every field required, unused ones null or [])."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Literal["bridge", "clarify", "more_activity"]
    topic: str | None = Field(max_length=80)
    grade: int | None = Field(ge=1, le=12)
    fields: list[ExposureField] = Field(max_length=3)
    clarifying_question: str | None = Field(max_length=200)
    extra_activity: str | None = Field(max_length=500)
    extra_activity_field: str | None = Field(max_length=60)
    extra_activity_materials: list[Material] = Field(max_length=6)
    spoken_text: str = Field(min_length=1, max_length=1500)

    @model_validator(mode="after")
    def _per_outcome(self) -> Self:
        extras = (self.extra_activity, self.extra_activity_field)
        if self.outcome == "bridge":
            _bridge_rules(self)
        elif self.outcome == "clarify":
            if not self.clarifying_question or self.fields or any(extras):
                raise ValueError("clarify: a clarifying_question only, no fields or activity")
        elif not (self.topic and all(extras)) or self.fields:
            raise ValueError("more_activity: topic, extra_activity and its field, no fields")
        return self


def _bridge_rules(bridge: ExposureBridge) -> None:
    if not bridge.topic or len(bridge.fields) != THREE_FIELDS:
        raise ValueError("bridge: a topic and exactly three fields")
    if not any(field.field_kind == "non_stem" for field in bridge.fields):
        raise ValueError("bridge: at least one field must be non_stem")
    if any(field.needs_electricity or field.needs_purchase for field in bridge.fields):
        raise ValueError("bridge: no activity may need electricity or a purchase")
    names = {field.field.strip().casefold() for field in bridge.fields}
    if len(names) != THREE_FIELDS:
        raise ValueError("bridge: the three fields must be different")
    if bridge.clarifying_question or bridge.extra_activity:
        raise ValueError("bridge: no clarifying_question or extra_activity")


THREE_FIELDS: Final = 3
EXPOSURE: Final = PromptSpec(prompt_id="exposure", output_type=ExposureBridge)
CHAPTER_EXAMPLES: Final = 8


class ExposureLayer:
    def __init__(
        self, llm: LanguageModel, registry: PromptRegistry, catalogue: ChapterCatalogue
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._catalogue = catalogue

    async def generate(
        self, ctx: TurnContext, user_text: str, interactive_ids: Sequence[str], register: Language
    ) -> LayerResult:
        """Raises ProviderError when the model can't give a valid bridge; DomainError when
        called for anyone but a teacher (a router bug)."""
        if ctx.profile.role is not Role.TEACHER:
            raise DomainError(f"exposure called for role {ctx.profile.role}")
        previous = ExposureLayer.previous_reply(ctx.recent_exchanges)
        wants_more = MORE_ACTIVITY in interactive_ids
        if NEW_CHAPTER in interactive_ids or (wants_more and previous is None):
            return ExposureLayer._ask_chapter(register)
        profile = ctx.profile
        subject = ChapterMatcher.subject_of(profile.subject)
        match = ChapterMatcher.match(user_text, profile.grade, subject, self._catalogue.books)
        titles = (
            ChapterMatcher.titles_for(
                profile.grade, subject, self._catalogue.books, CHAPTER_EXAMPLES
            )
            if match is None
            else []
        )
        rendered = self._registry.render(
            EXPOSURE,
            system_vars={
                "grade": str(profile.grade) if profile.grade else "not known",
                "subject": profile.subject or "not known",
                "district": profile.district or "not known",
                "chapter_hint": match.hint if match else "none",
                "chapter_titles": "; ".join(titles),
                "requested_mode": "the teacher pressed 'another activity'"
                if wants_more
                else "only if they asked for one",
                "language_rule": ParentQuestionLayer.LANGUAGE_RULES[register].replace(
                    "answer and try_this", "every text field"
                ),
                "spoken_rule": ParentQuestionLayer.SPOKEN_RULES[register],
            },
            user_vars={
                "previous_reply": previous or "none",
                "teacher_message": user_text or "(nothing said)",
            },
            semantic_check=lambda bridge: ExposureLayer.problems(bridge, register),
        )
        result = await self._llm.generate(rendered.request)
        return LayerResult(
            reply=ExposureLayer.render(result.output, register, profile.grade),
            usages=[result.usage],
            prompt_versions={EXPOSURE.prompt_id: rendered.request.prompt.prompt_version},
            outcome=StepOutcome.OK,
            degraded_reason=None,
            hazard_rule=None,
        )

    @staticmethod
    def previous_reply(exchanges: Sequence[Exchange]) -> str | None:
        """The latest exposure reply, for "another activity"; mentor turns are ignored."""
        for exchange in reversed(exchanges):
            if exchange.route is Route.EXPOSURE:
                return exchange.reply_text
        return None

    @staticmethod
    def problems(bridge: ExposureBridge, register: Language) -> list[str]:
        """s10 §4.4: no devices or purchases in an activity; no money in any field."""
        activities: list[str] = []
        texts: list[str] = []
        for field in bridge.fields:
            activities.extend([field.five_minute_activity, *field.activity_materials])
            texts.extend(
                [field.why_it_connects, field.example_from_india, field.local_hook, *field.careers]
            )
        activities.extend([bridge.extra_activity or "", *bridge.extra_activity_materials])
        texts.extend(activities)
        problems: list[str] = []
        if any(PhraseFinder.contains_any(text, DEVICE_OR_PURCHASE_WORDS) for text in activities):
            problems.append("activity: no projector, phone, internet, printout or buying")
        if any(
            MentorLayer.FACT_FIGURE.search(text) or PhraseFinder.contains_any(text, MONEY_WORDS)
            for text in texts
        ):
            problems.append("no salaries, money amounts, percentages or years")
        written = " ".join([bridge.topic or "", *texts, bridge.clarifying_question or ""])
        problems.extend(RegisterDetector.script_problems(written, bridge.spoken_text, register))
        return problems

    @staticmethod
    def render(bridge: ExposureBridge, register: Language, grade: int | None) -> CanonicalReply:
        """The body, by code: what matters first, plain text (no markdown) for the voice note."""
        labels = LABELS[register]
        buttons = list(EXPOSURE_BUTTONS[register])
        if bridge.outcome == "clarify":
            body = bridge.clarifying_question or ""
            buttons = []
        elif bridge.outcome == "more_activity":
            materials = ", ".join(bridge.extra_activity_materials)
            body = (
                f"{labels['another']}: {bridge.topic} ({bridge.extra_activity_field})\n"
                f"{bridge.extra_activity}\n{labels['materials']}: {materials or '-'}"
            )
        else:
            class_note = f" (class {bridge.grade or grade})" if (bridge.grade or grade) else ""
            names = ", ".join(field.field for field in bridge.fields)
            sections = [
                f"{labels['topic']}: {bridge.topic}{class_note}\n{labels['fields']}: {names}."
            ]
            for number, field in enumerate(bridge.fields, start=1):
                sections.append(
                    "\n".join(
                        [
                            f"{number}. {field.field}",
                            f"{labels['why']}: {field.why_it_connects}",
                            f"{labels['example']}: {field.example_from_india}",
                            f"{labels['activity']}: {field.five_minute_activity}",
                            f"{labels['materials']}: {', '.join(field.activity_materials) or '-'}",
                            f"{labels['careers']}: {', '.join(field.careers)}",
                            f"{labels['local']}: {field.local_hook}",
                        ]
                    )
                )
            body = "\n\n".join(sections)
        return CanonicalReply(
            body=body,
            body_language=register,
            spoken_text=bridge.spoken_text,
            citations=[],
            buttons=buttons,
            fixed_kind=None,
        )

    @staticmethod
    def _ask_chapter(register: Language) -> LayerResult:
        voice = Language.HINDI if register is Language.HINGLISH else register
        return LayerResult(
            reply=CanonicalReply(
                body=ASK_CHAPTER[register],
                body_language=register,
                spoken_text=ASK_CHAPTER[voice],
                citations=[],
                buttons=[],
                fixed_kind=None,
            ),
            usages=[],
            prompt_versions={},
            outcome=StepOutcome.OK,
            degraded_reason=None,
            hazard_rule=None,
        )
