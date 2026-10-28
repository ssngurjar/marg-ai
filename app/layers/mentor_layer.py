"""MentorLayer: a student's question answered only from official sources, or honestly not
(s12 §4.3).

1. Retrieve (S11): the student's words, or a rewrite when QUERY_REWRITE_ENABLED.
2. Nothing relevant → the prompt in don't-know mode: no sources, no claims. The same mode
   redirects a message that isn't about studies or the future (s12 §4.8).
3. Otherwise every fact is a claim citing the labels C1…Cn it came from. The check refuses an
   unknown label, a figure in the uncited fields, or the wrong script (one repair retry); if it
   still fails, reviewed don't-know copy goes out instead (DEGRADED).
4. The body is assembled by code: claims numbered [n] by first use, then the official sources.
The reply is written in the student's register (C3c); the spoken text carries no links or markers.
"""

import re
from dataclasses import dataclass, replace
from typing import Annotated, ClassVar, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.constants.student_copy import (
    CHILD_PROTECTION_LINE,
    DONT_KNOW_FALLBACK,
    FAMILY_PRESSURE_WORDS,
    MAKE_A_PLAN_BUTTON,
    SOURCES_LABEL,
)
from app.core.errors import ProviderResponseInvalid
from app.domain.enums import Language, StepOutcome
from app.domain.models.reply import CanonicalReply, Citation, ReplyButton
from app.domain.models.retrieval import RetrievalResult
from app.domain.models.turn import TurnContext
from app.domain.models.usage import StepUsage
from app.domain.rules.phrase_finder import PhraseFinder
from app.domain.rules.register_detector import RegisterDetector
from app.domain.rules.stage_rules import StageRules
from app.layers.layer_result import LayerResult
from app.layers.mentor_context import LabelledChunk, MentorContext, MentorContextBuilder
from app.layers.parent_question_layer import ParentQuestionLayer
from app.layers.query_rewriter import QueryRewriter
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel
from app.rag.retriever import Retriever

type SourceLabel = Annotated[str, StringConstraints(pattern=r"^C[1-9][0-9]?$")]


class MentorClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1, max_length=300)
    sources: list[SourceLabel] = Field(min_length=1, max_length=3)


class MentorAnswer(BaseModel):
    """The mentor's answer (strict schema: every field required, optional ones nullable)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    knows: bool
    opening: str = Field(min_length=1, max_length=200)
    claims: list[MentorClaim] = Field(max_length=6)
    guidance: str | None = Field(max_length=600)  # mentor 1.1.0: room for real paths
    next_question: str | None = Field(max_length=160)
    suggest_roadmap: bool
    spoken_text: str = Field(min_length=1, max_length=1500)


MENTOR: Final = PromptSpec(prompt_id="mentor", output_type=MentorAnswer)


@dataclass(frozen=True, slots=True)
class MentorSettings:
    query_rewrite_enabled: bool  # QUERY_REWRITE_ENABLED (B9)


@dataclass(frozen=True, slots=True)
class _Retrieved:
    result: RetrievalResult
    usages: list[StepUsage]
    versions: dict[str, str]
    degraded_reason: str | None


class MentorLayer:
    FACT_FIGURE: ClassVar[re.Pattern[str]] = re.compile(
        r"₹|\bRs\.?|\brupees?\b|%|\b(19|20)\d{2}\b|\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b",
        re.IGNORECASE,
    )
    """What looks like a fact in a field that cites nothing: money, a percentage, a year, a date."""
    ADULT_AGE: ClassVar[int] = 18
    GENDERED_SELF: ClassVar[tuple[str, ...]] = (
        "rahi hoon", "rahi hun", "raha hoon", "raha hun", "sakti hoon", "sakti hun",
        "sakta hoon", "sakta hun", "karungi", "karunga", "dungi", "dunga", "bataungi",
        "bataunga", "samajhti hoon", "samajhti hun", "samajhta hoon", "samajhta hun",
        "रही हूँ", "रहा हूँ", "सकती हूँ", "सकता हूँ", "करूँगी", "करूँगा", "दूँगी", "दूँगा",
    )  # fmt: skip
    """Marg speaking of itself with a gender (the prompt forbids it; the model slipped in the
    eval: "samajh rahi hun"). Matched as whole phrases."""

    def __init__(
        self,
        llm: LanguageModel,
        registry: PromptRegistry,
        retriever: Retriever,
        settings: MentorSettings,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._retriever = retriever
        self._rewriter = QueryRewriter(llm, registry)
        self._settings = settings

    async def answer(self, ctx: TurnContext, user_text: str, register: Language) -> LayerResult:
        """Raises ProviderError when the model can't answer, StoreError when the corpus can't be
        read (the turn then gets TRY_AGAIN_LATER)."""
        retrieved = await self.retrieve(ctx, user_text)
        relevant = [] if retrieved.result.nothing_relevant else retrieved.result.chunks
        context = MentorContextBuilder.build(ctx, relevant, user_text)
        rendered = self._registry.render(
            MENTOR,
            system_vars={
                "dont_know": not context.chunks,
                "sources": context.sources,
                "profile_block": context.profile_block,
                "language_rule": ParentQuestionLayer.LANGUAGE_RULES[register].replace(
                    "answer and try_this", "opening, claims, guidance and next_question"
                ),
                "spoken_rule": ParentQuestionLayer.SPOKEN_RULES[register],
            },
            user_vars={
                "memory": context.memory_block,
                "plan": context.plan_block,
                "recent_conversation": context.recent_conversation,
                "message": user_text,
            },
            semantic_check=lambda answer: MentorLayer.problems(answer, context, register),
        )
        versions = {**retrieved.versions, MENTOR.prompt_id: rendered.request.prompt.prompt_version}
        try:
            result = await self._llm.generate(rendered.request)
        except ProviderResponseInvalid:
            if not context.chunks:
                raise
            # The model kept citing what it wasn't given: say honestly that we don't know.
            fallback = replace(retrieved, versions=versions)
            return self._dont_know_fallback(ctx, user_text, register, fallback)
        answer = result.output
        reply = self.reply(answer, context, ctx, user_text, register)
        degraded = retrieved.degraded_reason
        return LayerResult(
            reply=reply,
            usages=[*retrieved.usages, result.usage],
            prompt_versions=versions,
            outcome=StepOutcome.DEGRADED if degraded else StepOutcome.OK,
            degraded_reason=degraded,
            hazard_rule=None,
        )

    async def retrieve(self, ctx: TurnContext, user_text: str) -> _Retrieved:
        grade = ctx.profile.grade
        usages: list[StepUsage] = []
        versions: dict[str, str] = {}
        degraded: str | None = None
        query = QueryRewriter.raw(user_text)
        if self._settings.query_rewrite_enabled:
            query, usage, failed = await self._rewriter.rewrite(
                user_text, ctx.recent_exchanges, grade
            )
            if usage is not None:
                usages.append(usage)
            degraded = failed
        result = await self._retriever.retrieve(query, grade)
        return _Retrieved(result, usages, versions, degraded or result.degraded_reason)

    @staticmethod
    def problems(answer: MentorAnswer, context: MentorContext, register: Language) -> list[str]:
        """The repair turn's fixed-vocabulary problems (s12 §4.3)."""
        given = {labelled.label for labelled in context.chunks}
        problems: list[str] = []
        if not given and (answer.knows or answer.claims):
            problems.append("no sources were given: set knows to false and claims to []")
        if given and answer.knows and not answer.claims:
            problems.append("knows is true: give at least one claim")
        if not answer.knows and answer.claims:
            problems.append("knows is false: claims must be []")
        unknown = sorted({label for claim in answer.claims for label in claim.sources} - given)
        if unknown:
            allowed = ", ".join(sorted(given)) or "none"
            problems.append(f"{', '.join(unknown)} were not provided; cite only {allowed}")
        for name, text in (("opening", answer.opening), ("guidance", answer.guidance or "")):
            if MentorLayer.FACT_FIGURE.search(text):
                problems.append(f"{name}: no amounts, percentages, years or dates")
        everything = " ".join(
            [
                answer.opening,
                answer.guidance or "",
                answer.next_question or "",
                answer.spoken_text,
            ]
        )
        if PhraseFinder.contains_any(everything, MentorLayer.GENDERED_SELF):
            problems.append("no gendered verbs about yourself: rephrase without 'main' as subject")
        if "http" in answer.spoken_text or re.search(r"\[|\bC\d\b", answer.spoken_text):
            problems.append("spoken_text: no links, labels or brackets")
        written = " ".join(
            [answer.opening, *(claim.text for claim in answer.claims), answer.guidance or ""]
        )
        problems.extend(RegisterDetector.script_problems(written, answer.spoken_text, register))
        return problems

    @staticmethod
    def reply(
        answer: MentorAnswer,
        context: MentorContext,
        ctx: TurnContext,
        user_text: str,
        register: Language,
    ) -> CanonicalReply:
        """The body, assembled by code: numbered claims, guidance, the question, the sources."""
        by_label = {labelled.label: labelled for labelled in context.chunks}
        numbers: dict[UUID, int] = {}  # one number per source document, by first use
        cited: list[LabelledChunk] = []
        claim_lines: list[str] = []
        for claim in answer.claims:
            markers: list[str] = []
            for label in claim.sources:
                document = by_label[label].chunk.document_id
                if document not in numbers:
                    numbers[document] = len(numbers) + 1
                    cited.append(by_label[label])
                markers.append(f"[{numbers[document]}]")
            claim_lines.append(f"{claim.text} {''.join(dict.fromkeys(markers))}")
        sections = [answer.opening]
        if claim_lines:
            sections.append("\n".join(claim_lines))
        sections.extend(part for part in (answer.guidance, answer.next_question) if part)
        spoken = answer.spoken_text
        if MentorLayer.needs_protection_line(ctx, user_text):
            sections.append(CHILD_PROTECTION_LINE[register])
            spoken = f"{spoken} {CHILD_PROTECTION_LINE[_voice_register(register)]}"
        if cited:
            source_lines = [
                f"{position}. {labelled.chunk.title} — {labelled.chunk.source_url}"
                for position, labelled in enumerate(cited, start=1)
            ]
            sections.append("\n".join([SOURCES_LABEL[register], *source_lines]))
        buttons: list[ReplyButton] = []
        if answer.suggest_roadmap and ctx.active_roadmap is None:
            buttons.append(MAKE_A_PLAN_BUTTON[register])
        return CanonicalReply(
            body="\n\n".join(sections),
            body_language=register,
            spoken_text=spoken,
            citations=[
                Citation(
                    title=labelled.chunk.title,
                    source_url=labelled.chunk.source_url,
                    chunk_id=labelled.chunk.chunk_id,
                )
                for labelled in cited
            ],
            buttons=buttons,
            fixed_kind=None,
        )

    @staticmethod
    def needs_protection_line(ctx: TurnContext, user_text: str) -> bool:
        """A student who may be under 18 mentions marriage (golden student-mentor-006)."""
        if not PhraseFinder.contains_any(user_text, FAMILY_PRESSURE_WORDS):
            return False
        learner = ctx.active_learner
        if learner is None:
            return True  # age unknown: the line is harmless, missing it isn't
        return StageRules.age_on(learner.birth_year, ctx.messages[-1].received_at.date()) < (
            MentorLayer.ADULT_AGE
        )

    def _dont_know_fallback(
        self,
        ctx: TurnContext,
        user_text: str,
        register: Language,
        retrieved: _Retrieved,
    ) -> LayerResult:
        voice = _voice_register(register)
        body, spoken = DONT_KNOW_FALLBACK[register], DONT_KNOW_FALLBACK[voice]
        if self.needs_protection_line(ctx, user_text):
            body = f"{body}\n\n{CHILD_PROTECTION_LINE[register]}"
            spoken = f"{spoken} {CHILD_PROTECTION_LINE[voice]}"
        return LayerResult(
            reply=CanonicalReply(
                body=body,
                body_language=register,
                spoken_text=spoken,
                citations=[],
                buttons=[],
                fixed_kind=None,
            ),
            usages=retrieved.usages,
            prompt_versions=retrieved.versions,
            outcome=StepOutcome.DEGRADED,
            degraded_reason="citations_dropped",
            hazard_rule=None,
        )


def _voice_register(register: Language) -> Language:
    """Hinglish is spoken from the Hindi text: the Hindi voice reads only Devanagari."""
    return Language.HINDI if register is Language.HINGLISH else register
