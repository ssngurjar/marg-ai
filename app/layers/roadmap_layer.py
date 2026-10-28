"""RoadmapLayer: a student's goal as 3-6 concrete, sourced steps (s12 §4.4).

    an active plan, plain request ("mera plan") → shown as stored, with a "New plan" button
    no plan, or rm:create / "naya plan"         → a new plan is drafted (RoadmapDraft)

A drafted plan is returned as a SaveRoadmap write, applied with the reply in finalize, so a reply
that safety blocks never leaves a plan behind. Every step naming a fact cites a source label;
a cost needs a source; at least one step is free this week (one repair retry). If retrieval finds
nothing relevant, no plan is drafted: the reply says so, with safe first steps (roadmap-003).
"""

from decimal import Decimal
from typing import ClassVar, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.constants.student_copy import (
    MAKE_A_PLAN,
    NEW_PLAN_BUTTON,
    NEW_PLAN_PHRASES,
    PLAN_UNVERIFIABLE,
    SOURCES_LABEL,
    YOUR_PLAN,
)
from app.domain.enums import Language, StepOutcome
from app.domain.models.reply import CanonicalReply, Citation
from app.domain.models.student import Roadmap
from app.domain.models.turn import TurnContext
from app.domain.models.writes import ResolvedRoadmapStep, SaveRoadmap
from app.domain.rules.phrase_finder import PhraseFinder
from app.domain.rules.register_detector import RegisterDetector
from app.layers.layer_result import LayerResult
from app.layers.mentor_context import LabelledChunk, MentorContext, MentorContextBuilder
from app.layers.mentor_layer import MentorLayer, SourceLabel
from app.layers.parent_question_layer import ParentQuestionLayer
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel


class RoadmapDraftStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: str = Field(min_length=1, max_length=160)
    timeframe: str = Field(min_length=1, max_length=40)
    cost_inr: Decimal | None = Field(ge=0)
    source: SourceLabel | None
    free_now: bool


class RoadmapDraft(BaseModel):
    """The model's plan (strict schema: every field required, optional ones nullable)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    goal: str = Field(min_length=1, max_length=80)
    steps: list[RoadmapDraftStep] = Field(min_length=3, max_length=6)
    spoken_text: str = Field(min_length=1, max_length=1500)


ROADMAP: Final = PromptSpec(prompt_id="roadmap", output_type=RoadmapDraft)


class RoadmapLayer:
    SHORT_REQUEST_WORDS: ClassVar[int] = 4
    """A request this short ("plan banao") is searched together with the student's ambitions."""

    def __init__(self, llm: LanguageModel, registry: PromptRegistry, mentor: MentorLayer) -> None:
        self._llm = llm
        self._registry = registry
        self._mentor = mentor

    async def handle(
        self,
        ctx: TurnContext,
        user_text: str,
        interactive_ids: list[str],
        register: Language,
    ) -> LayerResult:
        """Raises ProviderError when the plan can't be drafted, StoreError when the corpus can't
        be read (the turn then gets TRY_AGAIN_LATER)."""
        active = ctx.active_roadmap
        wants_new = MAKE_A_PLAN in interactive_ids or PhraseFinder.contains_any(
            user_text, NEW_PLAN_PHRASES
        )
        if active is not None and not wants_new:
            return RoadmapLayer.show(active, register)
        return await self._draft(ctx, user_text, register)

    @staticmethod
    def show(roadmap: Roadmap, register: Language) -> LayerResult:
        """The stored plan, as it was saved: no model call."""
        lines = [YOUR_PLAN[register].format(goal=roadmap.goal)]
        lines.extend(f"{step.position}. {step.action} — {step.timeframe}" for step in roadmap.steps)
        sources = [step.source_url for step in roadmap.steps if step.source_url is not None]
        body = "\n".join(lines)
        if sources:
            listed = "\n".join(f"- {url}" for url in dict.fromkeys(str(url) for url in sources))
            body = f"{body}\n\n{SOURCES_LABEL[register]}\n{listed}"
        return LayerResult(
            reply=CanonicalReply(
                body=body,
                body_language=register,
                spoken_text=None,
                citations=[],
                buttons=[NEW_PLAN_BUTTON[register]],
                fixed_kind=None,
            ),
            usages=[],
            prompt_versions={},
            outcome=StepOutcome.OK,
            degraded_reason=None,
            hazard_rule=None,
        )

    async def _draft(self, ctx: TurnContext, user_text: str, register: Language) -> LayerResult:
        search = RoadmapLayer.search_text(ctx, user_text)
        retrieved = await self._mentor.retrieve(ctx, search)
        if retrieved.result.nothing_relevant:
            return RoadmapLayer._unverifiable(register, retrieved.versions)
        context = MentorContextBuilder.build(ctx, retrieved.result.chunks, user_text)
        rendered = self._registry.render(
            ROADMAP,
            system_vars={
                "sources": context.sources,
                "profile_block": context.profile_block,
                "language_rule": ParentQuestionLayer.LANGUAGE_RULES[register].replace(
                    "answer and try_this", "goal, action and timeframe"
                ),
                "spoken_rule": ParentQuestionLayer.SPOKEN_RULES[register],
            },
            user_vars={
                "memory": context.memory_block,
                "recent_conversation": context.recent_conversation,
                "message": user_text,
            },
            semantic_check=lambda draft: RoadmapLayer.problems(draft, context, register),
        )
        result = await self._llm.generate(rendered.request)
        draft = result.output
        version = rendered.request.prompt.prompt_version
        write, reply = RoadmapLayer.resolved(draft, context, ctx, register, version)
        return LayerResult(
            reply=reply,
            usages=[*retrieved.usages, result.usage],
            prompt_versions={**retrieved.versions, ROADMAP.prompt_id: version},
            outcome=StepOutcome.DEGRADED if retrieved.degraded_reason else StepOutcome.OK,
            degraded_reason=retrieved.degraded_reason,
            writes=[write],
            hazard_rule=None,
        )

    @staticmethod
    def search_text(ctx: TurnContext, user_text: str) -> str:
        """What to search for: the request, plus the student's ambitions when it's just "plan"."""
        if len(PhraseFinder.words(user_text)) > RoadmapLayer.SHORT_REQUEST_WORDS:
            return user_text
        ambitions = ctx.memory.ambitions if ctx.memory else []
        return " ".join([user_text, *ambitions]) if ambitions else user_text

    @staticmethod
    def problems(draft: RoadmapDraft, context: MentorContext, register: Language) -> list[str]:
        given = {labelled.label for labelled in context.chunks}
        problems: list[str] = []
        unknown = sorted({step.source for step in draft.steps if step.source} - given)
        if unknown:
            problems.append(
                f"{', '.join(unknown)} were not provided; cite only {', '.join(sorted(given))}"
            )
        if any(step.cost_inr is not None and step.source is None for step in draft.steps):
            problems.append("a step with cost_inr needs a source")
        if not any(step.free_now for step in draft.steps):
            problems.append("at least one step must be free and doable this week (free_now)")
        if "http" in draft.spoken_text or "[" in draft.spoken_text:
            problems.append("spoken_text: no links, labels or brackets")
        written = " ".join([draft.goal, *(step.action for step in draft.steps)])
        problems.extend(RegisterDetector.script_problems(written, draft.spoken_text, register))
        return problems

    @staticmethod
    def resolved(
        draft: RoadmapDraft,
        context: MentorContext,
        ctx: TurnContext,
        register: Language,
        prompt_version: str,
    ) -> tuple[SaveRoadmap, CanonicalReply]:
        """The write (labels resolved to source pages) and the reply, both built by code."""
        by_label: dict[str, LabelledChunk] = {
            labelled.label: labelled for labelled in context.chunks
        }
        numbers: dict[UUID, int] = {}  # one number per source document, by first use
        cited: list[LabelledChunk] = []
        steps: list[ResolvedRoadmapStep] = []
        lines = [YOUR_PLAN[register].format(goal=draft.goal)]
        for position, step in enumerate(draft.steps, start=1):
            labelled = by_label.get(step.source) if step.source else None
            marker = ""
            if labelled is not None:
                document = labelled.chunk.document_id
                if document not in numbers:
                    numbers[document] = len(numbers) + 1
                    cited.append(labelled)
                marker = f" [{numbers[document]}]"
            source_url: HttpUrl | None = labelled.chunk.source_url if labelled else None
            steps.append(
                ResolvedRoadmapStep(
                    action=step.action,
                    timeframe=step.timeframe,
                    cost_inr=step.cost_inr if labelled else None,
                    source_url=source_url,
                )
            )
            lines.append(f"{position}. {step.action} — {step.timeframe}{marker}")
        body = "\n".join(lines)
        if cited:
            source_lines = [
                f"{number}. {labelled.chunk.title} — {labelled.chunk.source_url}"
                for number, labelled in enumerate(cited, start=1)
            ]
            body = f"{body}\n\n" + "\n".join([SOURCES_LABEL[register], *source_lines])
        active = ctx.active_roadmap
        write = SaveRoadmap(
            goal=draft.goal,
            steps=steps,
            abandon_roadmap_id=active.id if active else None,
            prompt_version=prompt_version,
        )
        reply = CanonicalReply(
            body=body,
            body_language=register,
            spoken_text=draft.spoken_text,
            citations=[
                Citation(
                    title=labelled.chunk.title,
                    source_url=labelled.chunk.source_url,
                    chunk_id=labelled.chunk.chunk_id,
                )
                for labelled in cited
            ],
            buttons=[],
            fixed_kind=None,
        )
        return write, reply

    @staticmethod
    def _unverifiable(register: Language, versions: dict[str, str]) -> LayerResult:
        voice = Language.HINDI if register is Language.HINGLISH else register
        return LayerResult(
            reply=CanonicalReply(
                body=PLAN_UNVERIFIABLE[register],
                body_language=register,
                spoken_text=PLAN_UNVERIFIABLE[voice],
                citations=[],
                buttons=[],
                fixed_kind=None,
            ),
            usages=[],
            prompt_versions=versions,
            outcome=StepOutcome.OK,
            degraded_reason=None,
            hazard_rule=None,
        )
