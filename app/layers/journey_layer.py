"""JourneyLayer: "Aaj ki Khoj" for parents of children aged 3-8 (s10b §4.4 to §4.9).

Flows, picked deterministically (mvp-scope C3b):
  A. today's khoj     `jrn:today[:<child>]`, or "aaj ki khoj", or right after onboarding
  B. report back      `jrn:done`, or any message or photo while an activity is open; a photo's
                      counts (SAM 3.1, read by the pipeline, s10b §4.14) reach the reflection
  C. another khoj     `jrn:other`: the open one is marked skipped, then A without it
  E. nudge settings   `nudge:08` / `nudge:18` / `nudge:off`, or "roz ka message band karo" /
                      "time badlo": NudgePreference and a fixed confirmation (s10b §4.11)
  D. parent question  everything else (ParentQuestionLayer), except the curiosity moment: a
                      message passing on the child's own question goes to
                      CuriosityMomentLayer first (s10b §4.15, C11)
The activity is chosen by rules (ActivityChooser); the model only rewords it for the family
(activity_personalise) or reflects on the child's report (parent_reflection, on Muse Spark Open).
Replies are written in the parent's register (C3c). Every activity reply ends with the
supervision line, added by code. If the model's text fails its checks, the reviewed catalogue
text goes out instead (DEGRADED), never an unchecked one.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import ClassVar, Final
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.constants.child_hazards import CHILD_HAZARD_WORDS
from app.constants.child_talk_copy import kid_start_button
from app.constants.journey_copy import (
    ADD_CHILD_BUTTON,
    AGE_COMING_SOON,
    ASK_LABEL,
    KHOJ_BUTTONS,
    KHOJ_DONE,
    KHOJ_OTHER,
    KHOJ_TODAY,
    LISTEN_LABEL,
    NO_ACTIVITY_LEFT,
    NUDGE_ASK,
    NUDGE_AT_8,
    NUDGE_AT_18,
    NUDGE_BUTTONS,
    NUDGE_OFF,
    NUDGE_OFF_REPLY,
    NUDGE_ON,
    NUDGE_TIME_NAMES,
    REFLECTION_FALLBACK,
    SUPERVISION_LINE,
    UNNAMED_CHILD,
    WHICH_CHILD,
)
from app.constants.journey_words import CAREER_WORDS, LABEL_WORDS
from app.core.errors import ProviderError
from app.domain.enums import ActivityStatus, AgeBand, Language, StepOutcome
from app.domain.models.activity import Activity, OfferedActivity, PastActivity
from app.domain.models.curiosity import CuriositySource, CuriositySourceKind
from app.domain.models.learner import Learner
from app.domain.models.photo import PhotoFindings
from app.domain.models.reply import CanonicalReply, ReplyButton
from app.domain.models.turn import TurnContext
from app.domain.models.usage import StepUsage
from app.domain.models.writes import (
    ActivityOffered,
    ActivityReported,
    NudgePreference,
    TurnWrite,
)
from app.domain.rules.activity_chooser import ActivityChooser
from app.domain.rules.activity_validator import ActivityValidator
from app.domain.rules.child_hazard_matcher import ChildHazardMatcher
from app.domain.rules.child_question_detector import ChildQuestionDetector
from app.domain.rules.conversation_machine import MAX_LEARNERS
from app.domain.rules.phrase_finder import PhraseFinder
from app.domain.rules.register_detector import RegisterDetector
from app.domain.rules.stage_rules import StageRules
from app.layers.activity_catalogue import CatalogueActivitySource
from app.layers.curiosity_moment_layer import CuriosityMomentLayer, NotAChildQuestion
from app.layers.layer_result import LayerResult
from app.layers.parent_question_layer import ParentQuestionLayer
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel


class ActivityPersonalisation(BaseModel):
    """The model's rewording of a reviewed activity (strict schema: every field required)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intro: str = Field(min_length=1, max_length=200)
    steps: list[str] = Field(min_length=1, max_length=6)
    questions_to_ask: list[str] = Field(min_length=2, max_length=4)
    listen_for: str = Field(min_length=1, max_length=160)
    parent_tip: str = Field(min_length=1, max_length=160)
    spoken_text: str = Field(min_length=1, max_length=1500)


class ParentReflection(BaseModel):
    """Serve and return on the parent's report (strict schema: every field required)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    praise_specific: str = Field(min_length=1, max_length=220)
    next_question: str = Field(min_length=1, max_length=160)
    parent_tip: str = Field(min_length=1, max_length=160)
    summary_for_record: str = Field(min_length=1, max_length=200)
    spoken_text: str = Field(min_length=1, max_length=900)


ACTIVITY_PERSONALISE: Final = PromptSpec(
    prompt_id="activity_personalise", output_type=ActivityPersonalisation
)
PARENT_REFLECTION: Final = PromptSpec(prompt_id="parent_reflection", output_type=ParentReflection)


@dataclass(frozen=True, slots=True)
class ParentMessage:
    """What the parent sent this turn: their words (typed, spoken or a caption), the buttons
    they tapped, and a checked photo of the child's work, only ever set while an activity is open
    (see `JourneyLayer.photo_phrases`)."""

    text: str
    interactive_ids: Sequence[str]
    photo: PhotoFindings | None = None


@dataclass(frozen=True, slots=True)
class JourneySettings:
    repeat_window: timedelta  # ACTIVITY_REPEAT_DAYS
    child_talk_enabled: bool = True  # CHILD_TALK_ENABLED: offer the "Main bachcha hoon" button


class JourneyLayer:
    KHOJ_PHRASES: ClassVar[tuple[str, ...]] = (
        "aaj ki khoj", "khoj", "nayi khoj", "activity", "today's khoj", "आज की खोज", "खोज",
    )  # fmt: skip
    NUDGE_OFF_PHRASES: ClassVar[tuple[str, ...]] = (
        "roz ka message band", "roz ka message band karo", "message band karo", "message mat bhejo",
        "daily message band", "stop the daily message", "रोज़ का संदेश बंद", "संदेश मत भेजो",
    )  # fmt: skip
    NUDGE_CHANGE_PHRASES: ClassVar[tuple[str, ...]] = (
        "time badlo", "samay badlo", "change time", "change the time", "roz message bhejo",
        "daily message", "समय बदलो", "रोज़ संदेश भेजो",
    )  # fmt: skip
    NUDGE_HOURS: ClassVar[dict[str, time]] = {NUDGE_AT_8: time(8, 0), NUDGE_AT_18: time(18, 0)}
    LANGUAGE_RULES: ClassVar[dict[Language, str]] = ParentQuestionLayer.LANGUAGE_RULES
    SPOKEN_RULES: ClassVar[dict[Language, str]] = ParentQuestionLayer.SPOKEN_RULES

    def __init__(
        self,
        llm: LanguageModel,
        registry: PromptRegistry,
        source: CatalogueActivitySource,
        parent_questions: ParentQuestionLayer,
        settings: JourneySettings,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._source = source
        self._parent_questions = parent_questions
        self._curiosity = CuriosityMomentLayer(llm, registry, source.materials)
        self._settings = settings

    async def handle(
        self, ctx: TurnContext, message: ParentMessage, now: datetime, register: Language
    ) -> LayerResult:
        """Raises ProviderError only from flow D (the parent question); A to C fall back to
        reviewed text instead."""
        user_text, photo = message.text, message.photo
        interactive_ids = message.interactive_ids
        button = interactive_ids[-1] if interactive_ids else None
        nudge_settings = self._nudge_settings(button, user_text, register)
        if nudge_settings is not None:
            return nudge_settings
        open_activity = self._offered(ctx)
        if button is not None and button.startswith(KHOJ_OTHER):
            return await self._another(ctx, open_activity, now, register)
        asks_for_khoj = PhraseFinder.contains_any(user_text, self.KHOJ_PHRASES)
        if (button is not None and button.startswith(KHOJ_TODAY)) or asks_for_khoj:
            return await self._today(ctx, ctx.active_learner, now, register, skipped=None)
        reported = button == KHOJ_DONE or bool(user_text.strip()) or photo is not None
        if open_activity is not None and reported:
            return await self._reflect(ctx, open_activity, user_text, register, photo)
        if button == KHOJ_DONE:
            # Nothing is open (it expired or was reported): offer today's khoj instead.
            return await self._today(ctx, ctx.active_learner, now, register, skipped=None)
        return await self._question(ctx, user_text, now, register)

    def photo_phrases(self, ctx: TurnContext) -> list[str] | None:
        """What to count in a photo of the open activity, or None when no activity is open (a
        photo is then not needed, s10b §4.14)."""
        open_activity = self._offered(ctx)
        if open_activity is None:
            return None
        return list(open_activity.activity.photo_count_phrases)

    async def _question(
        self, ctx: TurnContext, user_text: str, now: datetime, register: Language
    ) -> LayerResult:
        """D, or the curiosity moment when the parent passes on the child's own question.
        Raises ProviderError."""
        nicknames = [learner.nickname for learner in ctx.learners]
        not_the_childs: NotAChildQuestion | None = None
        if ChildQuestionDetector.relays_child_question(user_text, nicknames):
            moment = await self._curiosity.answer(
                ctx.active_learner, user_text, register, now.date()
            )
            if not isinstance(moment, NotAChildQuestion):
                return _with_curiosity(moment, ctx.active_learner, "relayed_question")
            not_the_childs = moment
        result = await self._parent_questions.answer(ctx, user_text, register)
        if not_the_childs is None:
            return result.model_copy(update={"hazard_rule": frozenset()})
        return result.model_copy(
            update={
                "hazard_rule": frozenset(),
                "usages": [not_the_childs.usage, *result.usages],
                "prompt_versions": {**not_the_childs.prompt_versions, **result.prompt_versions},
            }
        )

    async def first_khoj(
        self, ctx: TurnContext, learner: Learner, now: datetime, register: Language
    ) -> LayerResult:
        """The handoff right after onboarding (s08 §4.7): today's khoj for the new child."""
        return await self._today(ctx, learner, now, register, skipped=None)

    def _nudge_settings(
        self, button: str | None, user_text: str, register: Language
    ) -> LayerResult | None:
        """Flow E: the daily message turned on at a time, off, or the choice offered again."""
        if button in self.NUDGE_HOURS:
            hour = self.NUDGE_HOURS[button]
            confirmed = NUDGE_ON[register].format(time=NUDGE_TIME_NAMES[button][register])
            write = NudgePreference(enabled=True, local_time=hour)
            return _fixed(confirmed, register, ()).model_copy(update={"writes": [write]})
        turned_off = button == NUDGE_OFF or (
            button is None and PhraseFinder.contains_any(user_text, self.NUDGE_OFF_PHRASES)
        )
        if turned_off:
            write = NudgePreference(enabled=False, local_time=None)
            return _fixed(NUDGE_OFF_REPLY[register], register, ()).model_copy(
                update={"writes": [write]}
            )
        if button is None and PhraseFinder.contains_any(user_text, self.NUDGE_CHANGE_PHRASES):
            return _fixed(NUDGE_ASK[register], register, NUDGE_BUTTONS[register])
        return None

    def _offered(self, ctx: TurnContext) -> OfferedActivity | None:
        """The open activity with its catalogue entry; None if it's no longer in the catalogue."""
        record = ctx.open_activity
        if record is None:
            return None
        activity = self._source.find(record.activity_id)
        if activity is None:
            return None
        return OfferedActivity(
            learner_activity_id=record.learner_activity_id,
            learner_id=record.learner_id,
            activity=activity,
            offered_at=record.offered_at,
        )

    def _history(self, ctx: TurnContext) -> list[PastActivity]:
        """The active learner's past activities with their domains, newest first."""
        history: list[PastActivity] = []
        for record in ctx.activity_history:
            activity = self._source.find(record.activity_id)
            domains = activity.domains if activity else []
            history.append(
                PastActivity(
                    activity_id=record.activity_id,
                    domains=domains,
                    offered_at=record.offered_at,
                    status=record.status,
                )
            )
        return history

    # --- A and C: today's khoj -------------------------------------------------------------------

    async def _another(
        self,
        ctx: TurnContext,
        open_activity: OfferedActivity | None,
        now: datetime,
        register: Language,
    ) -> LayerResult:
        result = await self._today(ctx, ctx.active_learner, now, register, skipped=open_activity)
        if open_activity is None:
            return result
        skipped = ActivityReported(
            learner_activity_id=open_activity.learner_activity_id,
            status=ActivityStatus.SKIPPED,
            summary=None,
        )
        return result.model_copy(update={"writes": [skipped, *result.writes]})

    async def _today(
        self,
        ctx: TurnContext,
        learner: Learner | None,
        now: datetime,
        register: Language,
        skipped: OfferedActivity | None,
    ) -> LayerResult:
        if learner is None:
            return self._which_child(ctx, now, register)
        today = now.date()
        if StageRules.age_band(learner.birth_year, today) is not AgeBand.FOUNDATIONAL_3_8:
            return _fixed(AGE_COMING_SOON[register], register, buttons=())
        candidates = await self._source.candidates(learner, today)
        if skipped is not None:
            candidates = [item for item in candidates if item.id != skipped.activity.id]
        activity = ActivityChooser.choose(
            candidates, self._history(ctx), (), today, self._settings.repeat_window
        )
        if activity is None:
            return _fixed(NO_ACTIVITY_LEFT[register], register, buttons=())
        offered = ActivityOffered(
            learner_activity_id=uuid4(),
            learner_id=learner.id,
            activity_id=activity.id,
            activity_version=activity.version,
        )
        reviewed = _KhojText.from_activity(activity)
        personalised, usages, versions, problem = await self._personalise(
            activity, learner, now, register
        )
        kid = _kid_buttons(learner, register) if self._settings.child_talk_enabled else ()
        reviewed_reply = reviewed.reply(register, spoken=None, extra_buttons=kid)
        reply = (
            personalised.reply(register, spoken=personalised.spoken, extra_buttons=kid)
            if personalised
            else None
        )
        return LayerResult(
            reply=reply or reviewed_reply,
            usages=usages,
            prompt_versions=versions,
            outcome=StepOutcome.OK if reply else StepOutcome.DEGRADED,
            degraded_reason=None if reply else f"catalogue_fallback={problem}",
            writes=[offered],
            fallback_reply=reviewed_reply if reply else None,
            hazard_rule=frozenset(activity.hazards),
        )

    def _which_child(self, ctx: TurnContext, now: datetime, register: Language) -> LayerResult:
        """Several children and nothing says which: ask, one button per child (s10b §4.2)."""
        buttons: list[ReplyButton] = []
        for learner in ctx.learners[:MAX_LEARNERS]:
            age = StageRules.age_on(learner.birth_year, now.date())
            title = learner.nickname or UNNAMED_CHILD[register].format(age=age)
            buttons.append(ReplyButton(id=f"{KHOJ_TODAY}:{learner.id}", title=title[:20]))
        return _fixed(WHICH_CHILD[register], register, buttons=tuple(buttons))

    async def _personalise(
        self, activity: Activity, learner: Learner, now: datetime, register: Language
    ) -> tuple["_KhojText | None", list[StepUsage], dict[str, str], str | None]:
        rendered = self._registry.render(
            ACTIVITY_PERSONALISE,
            system_vars={
                "language_rule": self.LANGUAGE_RULES[register],
                "spoken_rule": self.SPOKEN_RULES[register],
                "title": activity.title,
                "child_age": StageRules.age_on(learner.birth_year, now.date()),
                "month": now.strftime("%B"),
                "materials": ", ".join(activity.materials) or "none",
                "steps": activity.steps,
                "questions": activity.questions_to_ask,
                "listen_for": activity.listen_for,
                "tips": activity.parent_tips,
            },
            user_vars={"child": learner.nickname or "", "last_report": ""},
            semantic_check=lambda output: _KhojChecks.problems(output, activity, register),
        )
        versions = {rendered.request.prompt.prompt_id: rendered.request.prompt.prompt_version}
        try:
            result = await self._llm.generate(rendered.request)
        except ProviderError as exc:
            return None, [], versions, type(exc).__name__
        return _KhojText.from_personalisation(result.output), [result.usage], versions, None

    # --- B: report back ----------------------------------------------------------------------

    async def _reflect(
        self,
        ctx: TurnContext,
        open_activity: OfferedActivity,
        report: str,
        register: Language,
        photo: PhotoFindings | None,
    ) -> LayerResult:
        activity = open_activity.activity
        learner = _learner_named(ctx.learners, open_activity)
        child_age = StageRules.age_on(learner.birth_year, open_activity.offered_at.date())
        rendered = self._registry.render(
            PARENT_REFLECTION,
            system_vars={
                "language_rule": self.LANGUAGE_RULES[register],
                "spoken_rule": self.SPOKEN_RULES[register],
                "title": activity.title,
                "child_age": child_age,
                "questions": activity.questions_to_ask,
                "listen_for": activity.listen_for,
                "photo_sent": photo is not None,
                "photo_counts": [
                    f"{found.count} {found.phrase}" for found in (photo.counts if photo else [])
                ],
            },
            user_vars={"child": learner.nickname or "", "parent_report": report or "Ho gaya"},
            semantic_check=lambda output: _ReflectionChecks.problems(output, register),
        )
        versions = {rendered.request.prompt.prompt_id: rendered.request.prompt.prompt_version}
        kid = _kid_buttons(learner, register) if self._settings.child_talk_enabled else ()
        buttons = (*self._after_report_buttons(ctx, register), *kid)
        try:
            result = await self._llm.generate(rendered.request)
        except ProviderError as exc:
            fallback = f"{REFLECTION_FALLBACK[register]}\n{activity.questions_to_ask[0]}"
            return _fixed(fallback, register, buttons).model_copy(
                update={
                    "prompt_versions": versions,
                    "outcome": StepOutcome.DEGRADED,
                    "degraded_reason": f"reflection_failed={type(exc).__name__}",
                    "writes": [_done(open_activity, summary=None, photo=photo)],
                    "hazard_rule": frozenset(activity.hazards),
                }
            )
        reflection = result.output
        body = (
            f"{reflection.praise_specific}\n\n{reflection.next_question}\n\n{reflection.parent_tip}"
        )
        return LayerResult(
            reply=CanonicalReply(
                body=body,
                body_language=register,
                spoken_text=reflection.spoken_text,
                citations=[],
                buttons=list(buttons),
                fixed_kind=None,
            ),
            usages=[result.usage],
            prompt_versions=versions,
            outcome=StepOutcome.OK,
            degraded_reason=None,
            writes=[_done(open_activity, summary=reflection.summary_for_record, photo=photo)],
            hazard_rule=frozenset(activity.hazards),
            curiosity=CuriositySource(
                learner_id=learner.id,
                kind="parent_report",
                hint_domains=list(activity.domains),
                activity_title=activity.title,
                activity_id=activity.id,
            ),
        )

    @staticmethod
    def _after_report_buttons(ctx: TurnContext, register: Language) -> tuple[ReplyButton, ...]:
        if len(ctx.learners) < MAX_LEARNERS:
            return (ADD_CHILD_BUTTON[register],)
        return ()


@dataclass(frozen=True, slots=True)
class _KhojText:
    """A khoj's parts, from the catalogue or the model, assembled by code (s10b §4.7)."""

    intro: str | None
    steps: Sequence[str]
    questions: Sequence[str]
    listen_for: str
    tip: str
    spoken: str | None

    @staticmethod
    def from_activity(activity: Activity) -> "_KhojText":
        return _KhojText(
            intro=activity.title,
            steps=activity.steps,
            questions=activity.questions_to_ask,
            listen_for=activity.listen_for,
            tip=activity.parent_tips[0],
            spoken=None,
        )

    @staticmethod
    def from_personalisation(output: ActivityPersonalisation) -> "_KhojText":
        return _KhojText(
            intro=output.intro,
            steps=output.steps,
            questions=output.questions_to_ask,
            listen_for=output.listen_for,
            tip=output.parent_tip,
            spoken=output.spoken_text,
        )

    def reply(
        self,
        register: Language,
        spoken: str | None,
        extra_buttons: Sequence[ReplyButton] = (),
    ) -> CanonicalReply:
        numbered = [f"{position}. {step}" for position, step in enumerate(self.steps, start=1)]
        questions = [f"• {question}" for question in self.questions]
        sections = [
            *([self.intro] if self.intro else []),
            "\n".join(numbered),
            "\n".join([ASK_LABEL[register], *questions]),
            f"{LISTEN_LABEL[register]} {self.listen_for}",
            self.tip,
            SUPERVISION_LINE[register],  # added by code, so a model can never drop it
        ]
        spoken_text = f"{spoken} {SUPERVISION_LINE[register]}" if spoken else None
        return CanonicalReply(
            body="\n\n".join(sections),
            body_language=register,
            spoken_text=spoken_text,
            citations=[],
            buttons=[*KHOJ_BUTTONS[register], *extra_buttons],
            fixed_kind=None,
        )


class _KhojChecks:
    """The personalisation's semantic check (s10b §4.7): fixed-vocabulary problems."""

    @staticmethod
    def problems(
        output: ActivityPersonalisation, activity: Activity, register: Language
    ) -> list[str]:
        problems: list[str] = []
        if len(output.steps) != len(activity.steps):
            problems.append(f"steps: expected exactly {len(activity.steps)} steps")
        texts = [output.intro, *output.steps, *output.questions_to_ask, output.listen_for]
        joined = " ".join([*texts, output.parent_tip])
        if ChildHazardMatcher.undeclared(joined, CHILD_HAZARD_WORDS, activity.hazards):
            problems.append("text: mentions a danger the activity doesn't include")
        if ActivityValidator.mentions_buying(texts):
            problems.append("text: asks for something to be bought")
        problems.extend(_ContentChecks.problems(joined))
        problems.extend(RegisterDetector.script_problems(joined, output.spoken_text, register))
        return problems


class _ReflectionChecks:
    @staticmethod
    def problems(output: ParentReflection, register: Language) -> list[str]:
        written = f"{output.praise_specific} {output.next_question} {output.parent_tip}"
        problems = _ContentChecks.problems(f"{written} {output.summary_for_record}")
        problems.extend(RegisterDetector.script_problems(written, output.spoken_text, register))
        return problems


class _ContentChecks:
    @staticmethod
    def problems(text: str) -> list[str]:
        problems: list[str] = []
        if PhraseFinder.contains_any(text, CAREER_WORDS):
            problems.append("text: mentions careers, jobs or exams")
        if PhraseFinder.contains_any(text, LABEL_WORDS):
            problems.append("text: labels the child")
        return problems


def _fixed(body: str, register: Language, buttons: Sequence[ReplyButton]) -> LayerResult:
    """A reply that needs no model: fixed copy, checked like any other reply."""
    return LayerResult(
        reply=CanonicalReply(
            body=body,
            body_language=register,
            spoken_text=None,
            citations=[],
            buttons=list(buttons),
            fixed_kind=None,
        ),
        usages=[],
        prompt_versions={},
        outcome=StepOutcome.OK,
        degraded_reason=None,
        hazard_rule=frozenset(),
    )


def _with_curiosity(
    result: LayerResult, learner: Learner | None, kind: CuriositySourceKind
) -> LayerResult:
    """Mark the turn for curiosity extraction (s13 §4.2), when we know which child it's about."""
    if learner is None:
        return result
    source = CuriositySource(learner_id=learner.id, kind=kind, hint_domains=[], activity_title=None)
    return result.model_copy(update={"curiosity": source})


def _kid_buttons(learner: Learner, register: Language) -> tuple[ReplyButton, ...]:
    """ "Main bachcha hoon 🙋" for a child whose parent switched child talk on (C13)."""
    if learner.child_talk_consented_at is None:
        return ()
    return (kid_start_button(str(learner.id), register),)


def _done(
    open_activity: OfferedActivity, summary: str | None, photo: PhotoFindings | None = None
) -> TurnWrite:
    return ActivityReported(
        learner_activity_id=open_activity.learner_activity_id,
        status=ActivityStatus.DONE,
        summary=summary,
        photo_counts=list(photo.counts) if photo is not None else None,
    )


def _learner_named(learners: Sequence[Learner], offered: OfferedActivity) -> Learner:
    for learner in learners:
        if learner.id == offered.learner_id:
            return learner
    raise ValueError("an open activity always belongs to one of the parent's learners")
