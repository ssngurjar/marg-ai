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

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import ClassVar, Final
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.constants.child_hazards import CHILD_HAZARD_WORDS
from app.constants.child_talk_copy import (
    OR_WORD,
    WHO_IS_WRITING,
    WHO_IS_WRITING_NO_CHILD,
    kid_start_button,
    named_kid_button,
)
from app.constants.journey_copy import (
    ACKNOWLEDGED,
    ADD_CHILD_BUTTON,
    ADD_CHILD_PROMPT,
    AGE_COMING_SOON,
    ASK_LABEL,
    CHILD_IN_HELLO,
    DELETE_DATA_BUTTON,
    DELETE_DATA_OFFER,
    DONE_THANKS,
    HELLO_NOTHING_OPEN,
    KHOJ_ABOUT,
    KHOJ_BUTTONS,
    KHOJ_DONE,
    KHOJ_OTHER,
    KHOJ_STILL_OPEN,
    KHOJ_TODAY,
    LISTEN_LABEL,
    NICKNAME_ONLY,
    NICKNAME_SAVED,
    NO_ACTIVITY_LEFT,
    NO_DETAILS_SUMMARY,
    NUDGE_ASK,
    NUDGE_AT_8,
    NUDGE_AT_18,
    NUDGE_BUTTONS,
    NUDGE_OFF,
    NUDGE_OFF_REPLY,
    NUDGE_ON,
    NUDGE_TIME_NAMES,
    ONE_MORE_KHOJ_BUTTON,
    REFLECTION_FALLBACK,
    SUPERVISION_LINE,
    TODAY_KHOJ_BUTTON,
    UNNAMED_CHILD,
    WHICH_CHILD,
    WHICH_KHOJ,
)
from app.constants.journey_words import CAREER_WORDS, LABEL_WORDS, SMALL_TALK
from app.constants.onboarding_copy import CHILD_FALLBACK, COPY
from app.constants.whatsapp import MAX_BUTTON_TITLE, MAX_BUTTONS
from app.core.errors import ProviderError
from app.domain.enums import (
    ActivityStatus,
    AgeBand,
    CopyKey,
    Language,
    ParentIntent,
    StepOutcome,
)
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
    LearnerUpsert,
    NudgePreference,
    TurnWrite,
)
from app.domain.rules.activity_chooser import ActivityChooser
from app.domain.rules.activity_validator import ActivityValidator
from app.domain.rules.child_hazard_matcher import ChildHazardMatcher
from app.domain.rules.child_question_detector import ChildQuestionDetector
from app.domain.rules.conversation_machine import MAX_LEARNERS
from app.domain.rules.onboarding_answer_parser import OnboardingAnswerParser
from app.domain.rules.phrase_finder import PhraseFinder
from app.domain.rules.register_detector import RegisterDetector
from app.domain.rules.stage_rules import StageRules
from app.layers.activity_catalogue import CatalogueActivitySource
from app.layers.curiosity_moment_layer import CuriosityMomentLayer, NotAChildQuestion
from app.layers.hazard_word_checks import HazardWordChecks
from app.layers.intent_reader import IntentRead, IntentReader
from app.layers.layer_result import LayerResult
from app.layers.local_voice import LocalVoice
from app.layers.parent_question_layer import ParentQuestionLayer
from app.layers.progress_report import ProgressRecord, ProgressReport
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
    spoken_text: str = Field(max_length=1500)


class ParentReflection(BaseModel):
    """Serve and return on the parent's report (strict schema: every field required)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    praise_specific: str = Field(min_length=1, max_length=220)
    next_question: str = Field(min_length=1, max_length=160)
    parent_tip: str = Field(min_length=1, max_length=160)
    summary_for_record: str = Field(min_length=1, max_length=200)
    spoken_text: str = Field(max_length=900)


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
    read_intent: bool = False  # INTENT_READING_ENABLED: Muse Spark reads a parent's free text


class JourneyLayer:
    RECENT_KHOJ: ClassVar[timedelta] = timedelta(hours=48)  # as long as a khoj stays open
    MAX_OTHER_KHOJS: ClassVar[int] = MAX_BUTTONS - 1  # the open khoj takes one button
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
        self._intents = IntentReader(llm, registry)
        self._settings = settings

    async def handle(
        self, ctx: TurnContext, message: ParentMessage, now: datetime, register: Language
    ) -> LayerResult:
        """Raises ProviderError only from flow D (the parent question); A to C fall back to
        reviewed text instead. Free text (no button, no photo) is read by Muse Spark into a
        ParentIntent when INTENT_READING_ENABLED; buttons, a bare greeting or thanks, and a
        failed reading go by the rules below."""
        open_activity = self._offered(ctx)
        free_text = not message.interactive_ids and message.photo is None and message.text.strip()
        if not (free_text and self._settings.read_intent) or JourneyLayer.small_talk(message.text):
            return await self._by_rules(ctx, message, open_activity, now, register)
        others = self._other_recent_khojs(ctx, open_activity, now)
        read = await self._intents.read(
            message.text,
            open_activity.activity.title if open_activity else None,
            ctx.learners,
            ctx.recent_exchanges,
            [other.activity.title for other in others],
        )
        if read.intent is None:
            result = await self._by_rules(ctx, message, open_activity, now, register)
        else:
            heard = ctx.model_copy(update={"heard_braj": True}) if read.braj else ctx
            spoken_in = read.asked_language or JourneyLayer.reply_language(
                register, read.language, message.text
            )
            turn = _FreeText(
                heard,
                message.text,
                open_activity,
                now,
                spoken_in,
                language_asked=read.asked_language is not None,
                child_name=read.child_name,
                report_about=read.report_about,
            )
            result = await self._by_intent(read.intent, turn)
        return _with_reading(result, read)

    @staticmethod
    def reply_language(chosen: Language, heard: Language | None, text: str) -> Language:
        """The rules read Roman text without a Hinglish marker word ("beta school jata",
        "aaj khana banaya") as English; the model hears it as Hinglish. Only that call is
        overruled: Devanagari stays Hindi, and the rules' Hinglish stays Hinglish (owner,
        2026-10-29)."""
        roman = (
            RegisterDetector.devanagari_share(text) or 0.0
        ) < RegisterDetector.DEVANAGARI_AT_MOST
        if chosen is Language.ENGLISH and heard is Language.HINGLISH and roman:
            return Language.HINGLISH
        return chosen

    async def _by_rules(
        self,
        ctx: TurnContext,
        message: ParentMessage,
        open_activity: OfferedActivity | None,
        now: datetime,
        register: Language,
    ) -> LayerResult:
        """Buttons and fixed phrases (the rules from before intent reading, kept as its fast
        path and its fallback)."""
        user_text, photo = message.text, message.photo
        interactive_ids = message.interactive_ids
        button = interactive_ids[-1] if interactive_ids else None
        settings = self._nudge_settings(
            button, user_text, register, khoj_open=open_activity is not None
        )
        if (
            settings is None
            and button is None
            and OnboardingAnswerParser.asks_to_add_child(user_text)
        ):
            # the router left "add a child" to the intent model (2026-11-01); this is its fallback
            settings = self._add_child(ctx, register)
        if settings is not None:
            return settings
        by_button = await self._khoj_button(ctx, button, open_activity, now, register)
        if by_button is not None:
            return by_button
        if PhraseFinder.contains_any(user_text, self.KHOJ_PHRASES):
            return await self._today(ctx, ctx.active_learner, now, register, skipped=None)
        said_something = bool(user_text.strip()) and not JourneyLayer.small_talk(user_text)
        reported = button == KHOJ_DONE or said_something or photo is not None
        if open_activity is not None and reported:
            return await self._report_by_rules(ctx, message, open_activity, now, register)
        if button == KHOJ_DONE:
            # Nothing is open (it expired or was reported): offer today's khoj instead.
            return await self._today(ctx, ctx.active_learner, now, register, skipped=None)
        return await self._question(ctx, user_text, now, register)

    async def _by_intent(  # noqa: PLR0911  # one return per intent
        self, intent: ParentIntent, turn: "_FreeText"
    ) -> LayerResult:
        """What code does for each reading; the model never picks a route itself."""
        ctx, user_text, open_activity = turn.ctx, turn.text, turn.open_activity
        now, register = turn.now, turn.register
        match intent:
            case ParentIntent.REPORT if open_activity is not None:
                return await self._report_in_words(turn, open_activity)
            case ParentIntent.CHILD_QUESTION:
                return await self._question(ctx, user_text, now, register, child_question=True)
            case ParentIntent.SMALL_TALK:
                return self._small_talk_reply(ctx, register, user_text)
            case ParentIntent.NEW_KHOJ | ParentIntent.ANOTHER_KHOJ | ParentIntent.SAME_KHOJ_AGAIN:
                return await self._khoj_asked(intent, turn)
            case ParentIntent.DAILY_TIME:
                return _fixed(NUDGE_ASK[register], register, NUDGE_BUTTONS[register])
            case ParentIntent.DAILY_OFF:
                return self._daily_off(register, khoj_open=open_activity is not None)
            case ParentIntent.SOMEONE_ELSE:
                return JourneyLayer._who_is_writing(ctx, now, register)
            case ParentIntent.PROGRESS:
                return self._progress(ctx, now, register)
            case ParentIntent.DELETE_DATA:
                return _fixed(
                    DELETE_DATA_OFFER[register], register, (DELETE_DATA_BUTTON[register],)
                )
            case ParentIntent.ADD_CHILD | ParentIntent.CHILD_TALK | ParentIntent.CHILD_NAME:
                about_a_child = self._about_a_child(intent, turn)
                if about_a_child is not None:
                    return about_a_child
                return await self._question(ctx, user_text, now, register, child_question=False)
            case _:
                # QUESTION, or a REPORT with nothing open: the parent's answer
                return await self._question(ctx, user_text, now, register, child_question=False)

    def _about_a_child(self, intent: ParentIntent, turn: "_FreeText") -> LayerResult | None:
        """Adding a child, child talk, or a child's home name; None: answer it as a question."""
        ctx, now, register = turn.ctx, turn.now, turn.register
        if intent is ParentIntent.ADD_CHILD:
            return self._add_child(ctx, register)
        if intent is ParentIntent.CHILD_TALK:
            if not self._settings.child_talk_enabled:
                return None
            return JourneyLayer._child_talk_offer(ctx, now, register)
        return JourneyLayer._child_named(ctx, turn.child_name, register)

    @staticmethod
    def _child_named(
        ctx: TurnContext, child_name: str | None, register: Language
    ) -> LayerResult | None:
        """ "Bacche ka naam Prisa hai": the home name saved for the child (owner, 2026-11-01),
        with onboarding's rules (short, never a full name). Several children and none chosen,
        or no name read: None, so the message is answered instead of guessed at."""
        child = ctx.active_learner or (ctx.learners[0] if len(ctx.learners) == 1 else None)
        if child is None or not child_name:
            return None
        parsed = OnboardingAnswerParser.parse_nickname(child_name)
        if parsed.nickname is None or len(parsed.nickname.split()) > 1:
            return _fixed(NICKNAME_ONLY[register], register, ())
        renamed = LearnerUpsert(
            learner_id=child.id,
            relation=child.relation,
            nickname=parsed.nickname,
            birth_year=child.birth_year,
        )
        saved = NICKNAME_SAVED[register].format(child=parsed.nickname)
        return _fixed(saved, register, ()).model_copy(update={"writes": [renamed]})

    async def _report_by_rules(
        self,
        ctx: TurnContext,
        message: ParentMessage,
        open_activity: OfferedActivity,
        now: datetime,
        register: Language,
    ) -> LayerResult:
        """A report by button, words or photo: on the open khoj, except a photo alone while
        another khoj is still waiting, which asks which one (owner, 2026-11-01)."""
        others = self._other_recent_khojs(ctx, open_activity, now)
        if message.photo is not None and not message.text.strip() and others:
            return JourneyLayer._which_khoj(open_activity, others, register)
        return await self._reflect(ctx, open_activity, message.text, register, message.photo)

    def _progress(self, ctx: TurnContext, now: datetime, register: Language) -> LayerResult:
        """ "How is my child doing?": the record, by code (owner, 2026-11-01)."""
        report = ProgressReport.text(
            ctx.learners,
            ProgressRecord(activities=ctx.all_activities, child_talk=ctx.child_talk_topics),
            find=self._source.find,
            now=now,
            register=register,
        )
        return _fixed(report, register, (TODAY_KHOJ_BUTTON[register],))

    async def _khoj_button(
        self,
        ctx: TurnContext,
        button: str | None,
        open_activity: OfferedActivity | None,
        now: datetime,
        register: Language,
    ) -> LayerResult | None:
        """Another khoj, which khoj a report was about, or today's; None for anything else."""
        if button is None:
            return None
        if button.startswith(KHOJ_OTHER):
            return await self._another(ctx, open_activity, now, register)
        if button.startswith(KHOJ_ABOUT):
            return await self._report_for_chosen_khoj(ctx, button, now, register)
        if button.startswith(KHOJ_TODAY):
            return await self._today(ctx, ctx.active_learner, now, register, skipped=None)
        return None

    # --- which khoj a report is about (owner, 2026-11-01) ----------------------------------------

    def _other_recent_khojs(
        self, ctx: TurnContext, open_activity: OfferedActivity | None, now: datetime
    ) -> list[OfferedActivity]:
        """Khojs offered to this child in the last 48 hours, not reported yet (still offered,
        or skipped for another), besides the open one: a report may be about one of them."""
        others: list[OfferedActivity] = []
        for record in ctx.activity_history:
            if record.status is ActivityStatus.DONE or now - record.offered_at > self.RECENT_KHOJ:
                continue
            if open_activity is not None and (
                record.learner_activity_id == open_activity.learner_activity_id
            ):
                continue
            activity = self._source.find(record.activity_id)
            if activity is not None:
                others.append(
                    OfferedActivity(
                        learner_activity_id=record.learner_activity_id,
                        learner_id=record.learner_id,
                        activity=activity,
                        offered_at=record.offered_at,
                    )
                )
        return others[: self.MAX_OTHER_KHOJS]

    @staticmethod
    def _which_khoj(
        open_activity: OfferedActivity, others: Sequence[OfferedActivity], register: Language
    ) -> LayerResult:
        buttons = tuple(
            ReplyButton(
                id=f"{KHOJ_ABOUT}:{offered.learner_activity_id}",
                title=JourneyLayer._button_title(offered.activity.title),
            )
            for offered in (open_activity, *others)
        )
        return _fixed(WHICH_KHOJ[register], register, buttons)

    @staticmethod
    def _button_title(title: str) -> str:
        """A khoj's title as a button (WhatsApp allows 20 characters)."""
        if len(title) <= MAX_BUTTON_TITLE:
            return title
        return title[: MAX_BUTTON_TITLE - 1].rstrip() + "…"

    async def _report_in_words(
        self, turn: "_FreeText", open_activity: OfferedActivity
    ) -> LayerResult:
        """A report in words: on the khoj it describes. When another khoj is still waiting and
        the reading can't tell which, Marg asks; the words come along with the answer."""
        ctx, user_text, register = turn.ctx, turn.text, turn.register
        others = self._other_recent_khojs(ctx, open_activity, turn.now)
        if not others:
            return await self._reflect(ctx, open_activity, user_text, register, None)
        for offered in (open_activity, *others):
            if turn.report_about == offered.activity.title:
                return await self._reflect(ctx, offered, user_text, register, None)
        return JourneyLayer._which_khoj(open_activity, others, register)

    async def _report_for_chosen_khoj(
        self, ctx: TurnContext, button: str, now: datetime, register: Language
    ) -> LayerResult:
        """The parent tapped which khoj their report was about: the reply is on that one, with
        the words they sent just before (a photo's counts aren't kept). An old or foreign id
        offers today's khoj."""
        chosen_id = button.removeprefix(f"{KHOJ_ABOUT}:")
        for record in ctx.activity_history:
            if str(record.learner_activity_id) != chosen_id:
                continue
            activity = self._source.find(record.activity_id)
            if activity is None:
                break
            chosen = OfferedActivity(
                learner_activity_id=record.learner_activity_id,
                learner_id=record.learner_id,
                activity=activity,
                offered_at=record.offered_at,
            )
            return await self._reflect(ctx, chosen, _words_before_which_khoj(ctx), register, None)
        return await self._today(ctx, ctx.active_learner, now, register, skipped=None)

    async def _khoj_asked(self, intent: ParentIntent, turn: "_FreeText") -> LayerResult:
        """A khoj asked for: today's, another one, or the open one again."""
        ctx, open_activity, now, register = turn.ctx, turn.open_activity, turn.now, turn.register
        if (
            open_activity is not None
            and turn.language_asked
            and intent is not ParentIntent.ANOTHER_KHOJ
        ):
            # "send khoj in hinglish": the open khoj in the language asked for, not a new one
            return await self._again_in(ctx, open_activity, now, register)
        if intent is ParentIntent.ANOTHER_KHOJ:
            return await self._another(ctx, open_activity, now, register)
        if intent is ParentIntent.SAME_KHOJ_AGAIN and open_activity is not None:
            return self._again(ctx, open_activity, register)
        return await self._today(ctx, ctx.active_learner, now, register, skipped=None)

    def _again(
        self, ctx: TurnContext, open_activity: OfferedActivity, register: Language
    ) -> LayerResult:
        """The open khoj once more, in its reviewed words: nothing new is offered."""
        activity = open_activity.activity
        learner = _learner_named(ctx.learners, open_activity)
        kid = _kid_buttons(learner, register) if self._settings.child_talk_enabled else ()
        reply = _KhojText.from_activity(activity).reply(register, spoken=None, extra_buttons=kid)
        return LayerResult(
            reply=reply,
            usages=[],
            prompt_versions={},
            outcome=StepOutcome.OK,
            degraded_reason=None,
            hazard_rule=frozenset(activity.hazards),
        )

    async def _again_in(
        self, ctx: TurnContext, open_activity: OfferedActivity, now: datetime, register: Language
    ) -> LayerResult:
        """The open khoj once more, reworded in the language the parent asked for (owner,
        2026-11-01): nothing new is offered. Falls back to the reviewed words."""
        activity = open_activity.activity
        learner = _learner_named(ctx.learners, open_activity)
        said = " ".join(message.text or "" for message in ctx.messages)
        personalised, usages, versions, problem = await self._personalise(
            activity,
            learner,
            now,
            register,
            LocalVoice.rule(register, ctx.profile.district, said, heard_braj=ctx.heard_braj),
        )
        kid = _kid_buttons(learner, register) if self._settings.child_talk_enabled else ()
        reviewed_reply = _KhojText.from_activity(activity).reply(
            register, spoken=None, extra_buttons=kid
        )
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
            fallback_reply=reviewed_reply if reply else None,
            hazard_rule=frozenset(activity.hazards),
        )

    @staticmethod
    def _child_talk_offer(
        ctx: TurnContext, now: datetime, register: Language
    ) -> LayerResult | None:
        """ "Can my child talk to you?": how to start, if the parent already said yes; else the
        same consent question onboarding asks, with its buttons (owner, 2026-11-01). None when
        no child on the list is 3-8 (child talk is for them): the question path answers."""
        young = [
            learner
            for learner in ctx.learners
            if StageRules.age_band(learner.birth_year, now.date()) is AgeBand.FOUNDATIONAL_3_8
        ]
        if not young:
            return None
        active = ctx.active_learner
        child = active if active is not None and active in young else young[0]
        values = {"child": child.nickname or CHILD_FALLBACK[register]}
        if child.child_talk_consented_at is not None:
            how_to_start = COPY[(CopyKey.CHILD_TALK_ENABLED, register)].body.format_map(values)
            return _fixed(how_to_start, register, _kid_buttons(child, register))
        ask = COPY[(CopyKey.ASK_CHILD_TALK, register)]
        buttons = tuple(
            ReplyButton(id=f"{button.id}:{child.id}", title=button.title) for button in ask.buttons
        )
        return _fixed(ask.body.format_map(values), register, buttons)

    def _small_talk_reply(
        self, ctx: TurnContext, register: Language, user_text: str
    ) -> LayerResult:
        """A greeting or thanks: the open khoj is still waiting, or today's khoj is offered.
        Fixed copy, no model: nothing to guess (owner's demo, 2026-10-29). An "ok" or "thanks"
        in the middle of a conversation answers what Marg just said: a short encouraging
        reply, never "Hello!" and the menu again (owner's demo, 2026-11-01)."""
        open_activity = self._offered(ctx)
        acknowledges = bool(ctx.recent_exchanges) and not OnboardingAnswerParser.is_greeting(
            user_text
        )
        if acknowledges:
            buttons = KHOJ_BUTTONS[register] if open_activity is not None else ()
            return _fixed(ACKNOWLEDGED[register], register, buttons)
        if open_activity is not None:
            waiting = KHOJ_STILL_OPEN[register].format(title=open_activity.activity.title)
            return _fixed(waiting, register, KHOJ_BUTTONS[register])
        learner = ctx.active_learner
        child = learner.nickname if learner and learner.nickname else CHILD_IN_HELLO[register]
        hello = HELLO_NOTHING_OPEN[register].format(child=child)
        return _fixed(hello, register, (TODAY_KHOJ_BUTTON[register],))

    @staticmethod
    def _who_is_writing(ctx: TurnContext, now: datetime, register: Language) -> LayerResult:
        """A child or student seems to be writing on the parent's phone: ask who, and answer
        no one the parent hasn't added (consent). The buttons are the children aged 3-8 on
        the list; tapping one starts child talk, or, without the parent's yes, asks them."""
        young = [
            learner
            for learner in ctx.learners
            if learner.nickname
            and StageRules.age_band(learner.birth_year, now.date()) is AgeBand.FOUNDATIONAL_3_8
        ]
        if not young:
            return _fixed(WHO_IS_WRITING_NO_CHILD[register], register, ())
        names = f" {OR_WORD[register]} ".join(str(learner.nickname) for learner in young)
        buttons = tuple(
            named_kid_button(str(learner.id), str(learner.nickname)) for learner in young
        )
        return _fixed(WHO_IS_WRITING[register].format(names=names), register, buttons)

    @staticmethod
    def _add_child(ctx: TurnContext, register: Language) -> LayerResult:
        if len(ctx.learners) >= MAX_LEARNERS:
            return _fixed(COPY[(CopyKey.MAX_CHILDREN, register)].body, register, ())
        return _fixed(ADD_CHILD_PROMPT[register], register, (ADD_CHILD_BUTTON[register],))

    @staticmethod
    def small_talk(text: str) -> bool:
        """Only a greeting or a thank-you ("Hi", "ok", "शुक्रिया"): not a report on a khoj."""
        if not text.strip():
            return False
        if OnboardingAnswerParser.is_greeting(text):
            return True
        said = " ".join(PhraseFinder.words(text))
        return said in {" ".join(PhraseFinder.words(phrase)) for phrase in SMALL_TALK}

    def photo_phrases(self, ctx: TurnContext) -> list[str] | None:
        """What to count in a photo of the open activity, or None when no activity is open (a
        photo is then not needed, s10b §4.14)."""
        open_activity = self._offered(ctx)
        if open_activity is None:
            return None
        return list(open_activity.activity.photo_count_phrases)

    async def _question(
        self,
        ctx: TurnContext,
        user_text: str,
        now: datetime,
        register: Language,
        *,
        child_question: bool | None = None,
    ) -> LayerResult:
        """D, or the curiosity moment when the parent passes on the child's own question.
        `child_question`: what intent reading said; None, the word rule decides. Raises
        ProviderError."""
        if JourneyLayer.small_talk(user_text):
            return self._small_talk_reply(ctx, register, user_text)
        nicknames = [learner.nickname for learner in ctx.learners]
        not_the_childs: NotAChildQuestion | None = None
        relayed = (
            ChildQuestionDetector.relays_child_question(user_text, nicknames)
            if child_question is None
            else child_question
        )
        if relayed:
            moment = await self._curiosity.answer(
                ctx.active_learner,
                user_text,
                register,
                now.date(),
                voice=LocalVoice.for_turn(register, ctx, user_text),
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
        self, button: str | None, user_text: str, register: Language, *, khoj_open: bool
    ) -> LayerResult | None:
        """Flow E: the daily message turned on at a time, off, or the choice offered again.
        The time question comes with the first khoj, so while a khoj is open the answer keeps
        its "Done" and "Another one" buttons (owner's judge walkthrough, 2026-10-29)."""
        after = KHOJ_BUTTONS[register] if khoj_open else ()
        if button in self.NUDGE_HOURS:
            hour = self.NUDGE_HOURS[button]
            confirmed = NUDGE_ON[register].format(time=NUDGE_TIME_NAMES[button][register])
            write = NudgePreference(enabled=True, local_time=hour)
            return _fixed(confirmed, register, after).model_copy(update={"writes": [write]})
        turned_off = button == NUDGE_OFF or (
            button is None and PhraseFinder.contains_any(user_text, self.NUDGE_OFF_PHRASES)
        )
        if turned_off:
            return JourneyLayer._daily_off(register, khoj_open=khoj_open)
        if button is None and PhraseFinder.contains_any(user_text, self.NUDGE_CHANGE_PHRASES):
            return _fixed(NUDGE_ASK[register], register, NUDGE_BUTTONS[register])
        return None

    @staticmethod
    def _daily_off(register: Language, *, khoj_open: bool) -> LayerResult:
        after = KHOJ_BUTTONS[register] if khoj_open else ()
        write = NudgePreference(enabled=False, local_time=None)
        return _fixed(NUDGE_OFF_REPLY[register], register, after).model_copy(
            update={"writes": [write]}
        )

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
        said = " ".join(message.text or "" for message in ctx.messages)
        personalised, usages, versions, problem = await self._personalise(
            activity,
            learner,
            now,
            register,
            LocalVoice.rule(register, ctx.profile.district, said, heard_braj=ctx.heard_braj),
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
        self,
        activity: Activity,
        learner: Learner,
        now: datetime,
        register: Language,
        voice: str,
    ) -> tuple["_KhojText | None", list[StepUsage], dict[str, str], str | None]:
        rendered = self._registry.render(
            ACTIVITY_PERSONALISE,
            system_vars={
                "language_rule": f"{self.LANGUAGE_RULES[register]} {voice}",
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
        kid = _kid_buttons(learner, register) if self._settings.child_talk_enabled else ()
        buttons = (*self._after_report_buttons(ctx, register), *kid)
        if not report.strip() and photo is None:
            # "Done" with nothing said: thanks and one question, by code (owner's demo,
            # 2026-11-01: the model's praise for a khoj nobody described read as absurd)
            child = learner.nickname or CHILD_IN_HELLO[register]
            thanks = _fixed(DONE_THANKS[register].format(child=child), register, buttons)
            return thanks.model_copy(
                update={"writes": [_done(open_activity, summary=NO_DETAILS_SUMMARY)]}
            )
        child_age = StageRules.age_on(learner.birth_year, open_activity.offered_at.date())
        rendered = self._registry.render(
            PARENT_REFLECTION,
            system_vars={
                "language_rule": LocalVoice.language_rule(
                    self.LANGUAGE_RULES[register], register, ctx, report
                ),
                "spoken_rule": self.SPOKEN_RULES[register],
                "title": activity.title,
                "child_age": child_age,
                "questions": activity.questions_to_ask,
                "listen_for": activity.listen_for,
                # no words (a "Done" tap, a photo alone): nothing to praise but the doing
                # (owner's demo, 2026-11-01: the reply invented what the child did)
                "reported": bool(report.strip()),
                "photo_sent": photo is not None,
                "photo_counts": [
                    f"{found.count} {found.phrase}" for found in (photo.counts if photo else [])
                ],
            },
            user_vars={"child": learner.nickname or "", "parent_report": report or "Ho gaya"},
            semantic_check=lambda output: _ReflectionChecks.problems(
                output, register, activity.hazards
            ),
        )
        versions = {rendered.request.prompt.prompt_id: rendered.request.prompt.prompt_version}
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
        """One more khoj. Adding a child after a report read as random (owner's demo,
        2026-11-01): it stays one message away ("add my son too")."""
        return (ONE_MORE_KHOJ_BUTTON[register],)


@dataclass(frozen=True, slots=True)
class _FreeText:
    """A parent's free text and what the journey knows while it reads it."""

    ctx: TurnContext
    text: str
    open_activity: OfferedActivity | None
    now: datetime
    register: Language
    language_asked: bool  # the parent asked for this reply's language ("in hindi")
    child_name: str | None  # child_name: the home name the parent gave
    report_about: str | None = None  # a report: the title of the khoj it describes


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
    def problems(
        output: ParentReflection, register: Language, declared: Collection[str]
    ) -> list[str]:
        written = f"{output.praise_specific} {output.next_question} {output.parent_tip}"
        problems = _ContentChecks.problems(f"{written} {output.summary_for_record}")
        problems.extend(RegisterDetector.script_problems(written, output.spoken_text, register))
        problems.extend(HazardWordChecks.problems(f"{written} {output.spoken_text}", declared))
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


def _words_before_which_khoj(ctx: TurnContext) -> str:
    """The report a parent sent just before Marg asked which khoj it was about, if any."""
    if not ctx.recent_exchanges:
        return ""
    last = ctx.recent_exchanges[-1]
    asked = any(last.reply_text.startswith(question) for question in WHICH_KHOJ.values())
    return last.user_text if asked else ""


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


def _with_reading(result: LayerResult, read: IntentRead) -> LayerResult:
    """The intent reading's usage and prompt version go with the turn's result; a failed
    reading (the rules decided instead) marks the turn DEGRADED."""
    update: dict[str, object] = {
        "usages": [read.usage, *result.usages] if read.usage else result.usages,
        "prompt_versions": {**read.prompt_versions, **result.prompt_versions},
    }
    if read.failed and result.outcome is StepOutcome.OK:
        update |= {"outcome": StepOutcome.DEGRADED, "degraded_reason": read.failed}
    return result.model_copy(update=update)
