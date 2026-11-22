"""ChildTalkLayer: a child talks to Marg.ai directly, with the parent's consent (s10b §4.16, C13).

    start    `kid:start[:<child>]` or "Main Munni hoon": consent, the child's daily limit and
             the cooldown are checked; a session opens (ChildSessionStart). A question in the
             same message is answered.
    turn     the child's message → child_talk prompt → a very short, true, kind reply in the
             child's register, ending "Mummy-Papa ko bhi batana" (added by code), voice always
    end      at the turn or time limit, or "bye"/"bas": a kind goodbye with a find-out activity,
             ChildSessionEnd, and a short summary for the parent (topics, never the child's words).
             When the child's time for the day runs out (ChildDailyLimitRules), their message is
             still answered in full, then the day's goodbye and the summary (DAILY_LIMIT)

Words no session rule decides are read for intent (ChildIntentReader; owner, 2026-11-20), once
safety_in has allowed them, while the answer is written: going ("main khelne ja rhi hoon") says
goodbye, a grown-up on the phone ("mummy aagyi") is asked to tap "Yes, I'm the parent", a
question before either is answered first; an unsure or failed reading leaves the rules' answer.

Inside a session nothing changes the account: deletion, adding a child and any other button get
"Mummy-Papa karenge" (C16). Asking for a language ("Hindi") changes only this session's replies.
A reply to a child follows what they asked for, then how they write, then the family's language;
a child who tapped their name on "Who's writing?" gets the message they came with answered.
Crisis in a child's words is handled before this layer, by the orchestrator, with child-worded
fixed text (s07).
"""

import asyncio
import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar, Final, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.constants.child_hazards import (
    CHILD_HAZARD_WORDS,
    CHILD_SAFE_TOOL_PHRASES,
    NEVER_TALK_ABOUT,
    TALKABLE_HAZARDS,
)
from app.constants.child_safety_words import (
    CHILD_MANIPULATION_PHRASES,
    CHILD_PERSONAL_TOPICS,
    QUESTION_WORDS,
)
from app.constants.child_talk_copy import (
    ASK_A_GROWNUP,
    CHILD_ACKNOWLEDGED,
    CHILD_ACKNOWLEDGED_AGAIN,
    CHILD_DAILY_LIMIT_REACHED,
    CHILD_FALLBACK,
    CHILD_GOODBYE,
    CHILD_GREETED,
    CHILD_HELLO,
    CHILD_LANGUAGE_SWITCHED,
    CHILD_OPENING_GOODBYE,
    CHILD_REFUSE_DANGER,
    CHILD_REFUSE_HURTING,
    CHILD_REFUSE_OTHER,
    CHILD_TALK_COOLDOWN,
    CHILD_TALK_NOT_ENABLED,
    CHILD_TALK_ON_BUTTON,
    DAILY_LIMIT_NAMES,
    PARENT_SUMMARY,
    PARENT_SUMMARY_NO_TOPICS,
    PARENT_TAKEOVER_ASK,
    PARENT_TAKEOVER_BUTTON,
    PARENT_TAKEOVER_DONE,
    PARENT_TALK_TIME,
    PARENT_TALK_TIME_NO_LIMIT,
    PARENT_TALK_TIME_USED_UP,
    TELL_YOUR_PARENTS,
    TOPIC_LABELS,
    UNNAMED_CHILD_NAME,
    WHICH_CHILD_IS_TALKING,
    WHO_IS_WRITING,
    minutes_said,
)
from app.constants.journey_words import CAREER_WORDS, EXPOSURE_PUSH_WORDS, LABEL_WORDS
from app.constants.onboarding_copy import CHILD_TALK_YES
from app.core.errors import ProviderResponseInvalid
from app.domain.enums import (
    ChildIntent,
    ChildSessionEndReason,
    CuriosityDomain,
    DailyTalkLimit,
    Language,
    LeavingReason,
    SafetyCategory,
    StepOutcome,
)
from app.domain.models.child_session import ChildSession, DailyTalkTime
from app.domain.models.curiosity import CuriositySource
from app.domain.models.learner import Learner
from app.domain.models.reply import CanonicalReply, ReplyButton
from app.domain.models.turn import Exchange, TurnContext
from app.domain.models.usage import StepUsage
from app.domain.models.writes import (
    ChildSessionEnd,
    ChildSessionLanguage,
    ChildSessionStart,
    ChildTalkTurn,
    TurnWrite,
)
from app.domain.rules.activity_validator import ActivityValidator
from app.domain.rules.child_daily_limit_rules import ChildDailyLimitRules
from app.domain.rules.child_hazard_matcher import ChildHazardMatcher
from app.domain.rules.child_question_detector import ChildQuestionDetector
from app.domain.rules.child_reply_matcher import ChildReplyMatcher
from app.domain.rules.child_session_rules import (
    KID_PARENT,
    KID_START,
    ChildSessionLimits,
    ChildSessionRules,
)
from app.domain.rules.child_talk_limit_parser import ChildTalkLimitParser
from app.domain.rules.onboarding_answer_parser import OnboardingAnswerParser
from app.domain.rules.parent_mention import ParentMention
from app.domain.rules.phrase_finder import PhraseFinder
from app.domain.rules.register_detector import RegisterDetector
from app.domain.rules.sentence_case import SentenceCase
from app.domain.rules.small_talk_rules import SmallTalkRules
from app.domain.rules.stage_rules import StageRules
from app.layers.child_intent_reader import ChildIntentRead, ChildIntentReader
from app.layers.layer_result import LayerResult
from app.layers.local_voice import LocalVoice
from app.layers.parent_question_layer import ParentQuestionLayer
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel


class ChildReply(BaseModel):
    """The model's reply to the child (strict schema: every field required)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    confident: bool
    answer: str = Field(min_length=1, max_length=240)
    find_out: str = Field(max_length=160)
    ask_back: str = Field(min_length=1, max_length=120)
    who_explores_this: str = Field(max_length=160)
    topic: CuriosityDomain | None
    spoken_text: str = Field(max_length=900)


CHILD_TALK: Final = PromptSpec(prompt_id="child_talk", output_type=ChildReply)
CHILD_REDIRECT: Final = PromptSpec(prompt_id="child_redirect", output_type=ChildReply)
type RedirectReason = Literal["hurting", "weapons", "rules", "unanswered"]
YOUNGEST_BAND_MAX_AGE: Final = 5  # 3-5: at most 8 words a sentence; 6-8: at most 12


@dataclass(frozen=True, slots=True)
class _Answer:
    text: CanonicalReply
    topic: CuriosityDomain | None
    usages: list[StepUsage]
    prompt_versions: dict[str, str]
    degraded_reason: str | None
    child_reply: ChildReply | None = None  # what the model wrote; None: fixed text

    def without_question(self, register: Language) -> "_Answer":
        """The answer in the last-answer style, made by code from what the model wrote: its
        question back left out, written and spoken, since a goodbye follows (owner,
        2026-11-20: one model call). Fixed text (the fallback) is reviewed copy, kept as is."""
        if self.child_reply is None:
            return self
        return dataclasses.replace(self, text=_ChildText.last_answer(self.child_reply, register))


@dataclass(frozen=True, slots=True)
class _Today:
    """The child's day so far: whether their time is used up, and what the parent's summary
    would say if the session ended now."""

    reached: bool
    talk_time: DailyTalkTime


@dataclass(frozen=True, slots=True)
class _SessionTurn:
    """A child's words in an open session that no rule decided: what the reading and the answer
    need."""

    ctx: TurnContext
    session: ChildSession
    learner: Learner
    text: str
    now: datetime
    register: Language
    voice: str
    today: _Today

    @property
    def recent(self) -> Sequence[Exchange]:
        return self.ctx.recent_exchanges

    @property
    def previous_reply(self) -> str | None:
        return self.recent[-1].reply_text if self.recent else None


class ChildTalkLayer:
    WORDS_PER_SENTENCE: ClassVar[dict[Literal["young", "older"], int]] = {"young": 8, "older": 12}
    REDIRECT_REASONS: ClassVar[dict[SafetyCategory, RedirectReason]] = {
        SafetyCategory.VIOLENT_CRIMES: "hurting",
        SafetyCategory.INDISCRIMINATE_WEAPONS: "weapons",
        SafetyCategory.NON_VIOLENT_CRIMES: "rules",
    }
    """A child's message blocked only for these gets a model-written redirect instead of a fixed
    refusal (owner, 2026-10-28: "think of how a human mentor would reply"). Everything else
    blocked (sexual content, medical, privacy…) keeps the fixed child refusal."""
    _REASON_ORDER: ClassVar[tuple[RedirectReason, ...]] = ("hurting", "weapons", "rules")

    LAST_ANSWER_RULE: ClassVar[str] = (
        "This is the child's last question for today, and a goodbye follows your reply: ask"
        ' nothing. Make ask_back one warm line to keep wondering about on their own ("Kal'
        ' Mummy ko batana tumne kya dekha!"), with no "?" anywhere, and ask nothing in'
        " spoken_text either."
    )
    """On the session's last answer (owner's eval, 2026-10-29: a question back, then "bye")."""
    INTRODUCTION_WORDS: ClassVar[int] = 4  # "Hi, main Munni hoon": longer says something more
    CARRY_WINDOW: ClassVar[timedelta] = timedelta(minutes=10)
    """How long after "Who's writing?" a tapped name still brings the child's message along."""

    def __init__(
        self,
        llm: LanguageModel,
        registry: PromptRegistry,
        limits: ChildSessionLimits,
        intents: ChildIntentReader | None = None,
    ) -> None:
        """`intents`: None when INTENT_READING_ENABLED is off; the rules then decide alone."""
        self._llm = llm
        self._registry = registry
        self._limits = limits
        self._intents = intents

    async def handle(  # noqa: PLR0913  # plus the input check's verdict (owner, 2026-10-28)
        self,
        ctx: TurnContext,
        user_text: str,
        interactive_ids: Sequence[str],
        now: datetime,
        register: Language,
        *,
        blocked: frozenset[SafetyCategory] = frozenset(),
        input_cleared: asyncio.Event | None = None,
    ) -> LayerResult:
        """Raises ProviderError when the model can't be reached (the orchestrator answers).
        `blocked`: the input check blocked the child's message for these (all in
        REDIRECT_REASONS): the turn gets a redirect, never an answer to what was asked.
        `input_cleared`: set by the orchestrator when safety_in allows the message; the intent
        reading never starts before it (owner, 2026-11-20). None: the words aren't read."""
        session = ctx.child_session
        if session is None:
            return await self._start(
                ctx,
                user_text,
                interactive_ids,
                now,
                register,
                blocked=blocked,
                input_cleared=input_cleared,
            )
        learner = _learner(ctx.learners, session.learner_id)
        previous = ctx.recent_exchanges[-1].reply_text if ctx.recent_exchanges else None
        today = _Today(
            reached=ChildDailyLimitRules.is_reached(
                learner, ctx.child_talk_today, now, self._limits
            ),
            talk_time=ChildDailyLimitRules.talk_time(
                learner, ctx.child_talk_today, session.started_at, now, self._limits
            ),
        )
        # the words are read when there are words, clearance will come, and it isn't a redirect
        readable = input_cleared is not None and not blocked and bool(user_text.strip())
        reader = self._intents if readable else None
        control = self._session_control(
            session,
            learner,
            user_text,
            interactive_ids,
            now=now,
            register=register,
            previous_reply=previous,
            today=today,
            read=reader is not None,
        )
        if control is not None:
            return control
        voice = LocalVoice.for_turn(register, ctx, user_text)
        if reader is not None and input_cleared is not None:
            turn = _SessionTurn(ctx, session, learner, user_text, now, register, voice, today)
            return await self._turn_as_read(turn, reader, input_cleared)
        return await self._turn(
            session,
            learner,
            user_text,
            now,
            register,
            voice=voice,
            blocked=blocked,
            today=today,
        )

    def _session_control(  # noqa: PLR0913, PLR0911  # one return per rule, in order
        self,
        session: ChildSession,
        learner: Learner,
        user_text: str,
        interactive_ids: Sequence[str],
        *,
        now: datetime,
        register: Language,
        previous_reply: str | None,
        today: _Today,
        read: bool = False,
    ) -> LayerResult | None:
        """What ends or steers the session before anything is answered: the parent taking the
        phone back, an account action, the limits, a goodbye, a parent's words, a language.
        None: the child's message is answered (and, with the day's time used up, the session
        then ends: `_turn`). `read`: the words will be read for intent, which then decides
        whether the child named in the third person ("Munni ne aaj kya kiya") is a grown-up."""
        if KID_PARENT in interactive_ids:
            return self._parent_took_over(session, learner, register, today.talk_time)
        if ChildTalkLayer._is_account_action(user_text, interactive_ids, learner):
            return _fixed(ASK_A_GROWNUP, register)
        if ChildSessionRules.is_over(session, now, self._limits):
            return self._goodbye(
                session, learner, register, ChildSessionEndReason.TIME_LIMIT, today
            )
        small_talk = SmallTalkRules.kind(user_text)
        if ChildSessionRules.says_goodbye(user_text) or small_talk in {"good_night", "goodbye"}:
            return self._goodbye(
                session, learner, register, ChildSessionEndReason.CHILD_ENDED, today
            )
        if today.reached and small_talk in {"thanks", "greeting"}:
            # the day's time is used up and there is nothing to answer: the day's goodbye now
            return self._goodbye(
                session, learner, register, ChildSessionEndReason.DAILY_LIMIT, today
            )
        if small_talk == "thanks":
            # an "ok" or emoji: answered at once and not counted as a question (2026-11-02)
            return ChildTalkLayer._acknowledged(register, previous_reply)
        if small_talk == "greeting":
            return _fixed(CHILD_GREETED, register)
        names_the_child = ChildSessionRules.names_the_child(user_text, learner.nickname)
        if ChildSessionRules.speaks_as_parent(user_text) or (names_the_child and not read):
            return ChildTalkLayer._takeover_ask(learner, register)
        asked = OnboardingAnswerParser.language_named(user_text)
        if asked is not None:
            return ChildTalkLayer._language_switched(session, asked)
        return None

    @staticmethod
    def _acknowledged(register: Language, previous_reply: str | None) -> LayerResult:
        """An ok or thanks: a quick fixed reply, said differently if Marg just said it."""
        repeated = SmallTalkRules.repeats(CHILD_ACKNOWLEDGED[register], previous_reply)
        return _fixed(CHILD_ACKNOWLEDGED_AGAIN if repeated else CHILD_ACKNOWLEDGED, register)

    @staticmethod
    def _takeover_ask(learner: Learner, register: Language) -> LayerResult:
        """ "Is this Mummy or Papa?" with the button. Only asks: a child typing it can't reach
        the parent's side without the button."""
        button = ReplyButton(id=KID_PARENT, title=PARENT_TAKEOVER_BUTTON[register])
        name = learner.nickname or UNNAMED_CHILD_NAME[register]
        return _fixed(PARENT_TAKEOVER_ASK, register, (button,), name=name)

    @staticmethod
    def _language_switched(session: ChildSession, asked: Language) -> LayerResult:
        """This session's replies in the language asked for; the account is unchanged (C16)."""
        switched = _fixed(CHILD_LANGUAGE_SWITCHED, asked)
        language = ChildSessionLanguage(session_id=session.id, language=asked)
        return switched.model_copy(update={"writes": [language]})

    @staticmethod
    def language_for(ctx: TurnContext, child_words: str, family_language: Language) -> Language:
        """The language of a reply to a child (owner, 2026-10-29): the one they ask for now
        ("Hindi") or asked for earlier in this session; else Hindi words in how they write
        (Devanagari → Hindi, Roman → Hinglish); else the family's. Roman words with no Hindi
        marker aren't evidence of English: "Main Munni hoon" has none."""
        asked = OnboardingAnswerParser.language_named(child_words)
        if asked is not None:
            return asked
        session = ctx.child_session
        if session is not None and session.language is not None:
            return session.language
        written_in = RegisterDetector.detect(child_words)
        if written_in in {Language.HINDI, Language.HINGLISH}:
            return written_in
        return family_language

    @staticmethod
    def words_before_the_name(
        ctx: TurnContext, user_text: str, interactive_ids: Sequence[str], now: datetime
    ) -> str:
        """A child who wrote ("me Munni hoon, aaj kya karein"), was asked "Who's writing?" and
        tapped their name: the message they came with, so it gets answered. "" otherwise."""
        tapped_name = any(button.startswith(KID_START) for button in interactive_ids)
        if user_text or not tapped_name or not ctx.recent_exchanges:
            return ""
        last = ctx.recent_exchanges[-1]
        if now - last.at > ChildTalkLayer.CARRY_WINDOW:
            return ""
        for question in WHO_IS_WRITING.values():
            if last.reply_text.startswith(question.split("{names}")[0]):
                return last.user_text
        return ""

    @staticmethod
    def redirects(categories: frozenset[SafetyCategory]) -> bool:
        """A blocked child message gets a redirect only when every category allows one."""
        return bool(categories) and categories <= frozenset(ChildTalkLayer.REDIRECT_REASONS)

    # --- start --------------------------------------------------------------------------------

    async def _start(  # noqa: PLR0913  # handle's inputs, passed on
        self,
        ctx: TurnContext,
        user_text: str,
        interactive_ids: Sequence[str],
        now: datetime,
        register: Language,
        *,
        blocked: frozenset[SafetyCategory],
        input_cleared: asyncio.Event | None = None,
    ) -> LayerResult:
        learner = ChildSessionRules.chosen_learner(interactive_ids, user_text, ctx.learners)
        if learner is None:
            return _fixed(WHICH_CHILD_IS_TALKING, register)
        name = learner.nickname or UNNAMED_CHILD_NAME[register]
        if learner.child_talk_consented_at is None:
            button = ReplyButton(
                id=f"{CHILD_TALK_YES}:{learner.id}", title=CHILD_TALK_ON_BUTTON[register]
            )
            return _fixed(CHILD_TALK_NOT_ENABLED, register, (button,), name=name)
        if ChildDailyLimitRules.is_reached(learner, ctx.child_talk_today, now, self._limits):
            # before the cooldown: "tomorrow", not "a little later", is what's true
            return _fixed(CHILD_DAILY_LIMIT_REACHED, register)
        if ChildSessionRules.in_cooldown(ctx.last_child_session_ended_at, now, self._limits):
            return _fixed(CHILD_TALK_COOLDOWN, register)
        session = ChildSession(
            id=uuid4(), learner_id=learner.id, started_at=now, turns_count=0, topics=[]
        )
        start = ChildSessionStart(session_id=session.id, learner_id=learner.id)
        opening = None if blocked else self._opening(session, learner, user_text, register)
        if opening is not None:
            return opening.model_copy(update={"writes": [start, *opening.writes]})
        voice = LocalVoice.for_turn(register, ctx, user_text)
        # the day's time isn't used up (checked above); the new session has used none of it
        today = _Today(
            reached=False,
            talk_time=ChildDailyLimitRules.talk_time(
                learner, ctx.child_talk_today, now, now, self._limits
            ),
        )
        readable = input_cleared is not None and not blocked and bool(user_text.strip())
        if readable and input_cleared is not None and self._intents is not None:
            turn = _SessionTurn(ctx, session, learner, user_text, now, register, voice, today)
            result = await self._opening_as_read(turn, self._intents, input_cleared)
        else:
            result = await self._turn(
                session,
                learner,
                user_text,
                now,
                register,
                voice=voice,
                blocked=blocked,
                today=today,
            )
        return result.model_copy(update={"writes": [start, *result.writes]})

    async def _opening_as_read(
        self, turn: _SessionTurn, intents: ChildIntentReader, input_cleared: asyncio.Event
    ) -> LayerResult:
        """An opening that says more than the introduction, read for intent (once safety_in
        allows it) alongside its answer. Going ("Main Munni hoon, ab man nahi hai") opens the
        session, then a goodbye for why they're going, with no summary: nothing was asked
        (owner, 2026-11-20).
        Any other reading, unsure or failed: answered, as before. Several things in one
        opening (a question and a language, a question and going) wait (decisions log)."""
        answering = asyncio.create_task(self._answer_for(turn, turn.register, turn.voice))
        try:
            read = await ChildTalkLayer._read(intents, turn, input_cleared)
            if read.intent is ChildIntent.LEAVING:
                result = ChildTalkLayer._opening_goodbye(turn, read.leaving_reason)
            else:
                answer = await answering
                ending = self._ending(turn.session, daily_reached=turn.today.reached)
                result = self._answered(
                    turn.session, turn.learner, turn.register, answer, turn.today, ending=ending
                )
        finally:
            await _discard_unused(answering)
        return _with_child_reading(result, read)

    @staticmethod
    def _opening_goodbye(turn: _SessionTurn, reason: LeavingReason | None) -> LayerResult:
        """ "Namaste Munni! Theek hai, abhi man nahi hai toh koi baat nahi…": a hello by name,
        okay, a kind line for why they're going, and telling Mummy-Papa. Not CHILD_GOODBYE's
        "Aaj bahut maza aaya!": nothing was talked about (owner, 2026-11-20)."""
        copy = CHILD_OPENING_GOODBYE[reason or LeavingReason.OTHER]
        name = turn.learner.nickname or UNNAMED_CHILD_NAME[turn.register]
        goodbye = _fixed(copy, turn.register, name=name)
        ended = ChildSessionEnd(
            session_id=turn.session.id, reason=ChildSessionEndReason.CHILD_ENDED
        )
        return goodbye.model_copy(update={"writes": [ended]})

    def _opening(
        self, session: ChildSession, learner: Learner, user_text: str, register: Language
    ) -> LayerResult | None:
        """An opening with nothing to answer: a language asked for beside the introduction
        ("Main Munni hoon, English mein baat karo") gets the switch (owner, 2026-11-20); only
        "Main Munni hoon" gets the hello. None: the opening says more, and is answered
        ("…mujhe gaali seekhni hai"; owner's second demo, 2026-11-01)."""
        asked = OnboardingAnswerParser.language_named_besides(
            user_text, ChildSessionRules.introduction_words(learner)
        )
        if asked is not None:
            return ChildTalkLayer._language_switched(session, asked)
        says_more = len(PhraseFinder.words(user_text)) > self.INTRODUCTION_WORDS
        if ChildQuestionDetector.asks(user_text) or says_more:
            return None
        name = learner.nickname or UNNAMED_CHILD_NAME[register]
        return _fixed(CHILD_HELLO, register, name=name)

    # --- a turn and the goodbye -------------------------------------------------------------------

    async def _turn(  # noqa: PLR0913  # plus the turn's local voice (owner, 2026-10-28)
        self,
        session: ChildSession,
        learner: Learner,
        user_text: str,
        now: datetime,
        register: Language,
        *,
        voice: str,
        blocked: frozenset[SafetyCategory] = frozenset(),
        today: _Today,
    ) -> LayerResult:
        ending = self._ending(session, daily_reached=today.reached)
        if blocked:
            reason = ChildTalkLayer._reason(blocked)
            answer = await self._redirect(
                learner, user_text, now, register, voice=voice, reason=reason
            )
        else:
            answer = await self._answer(
                learner,
                user_text,
                now,
                register,
                voice,
                last_answer=ending is not None,
                first_answer=session.turns_count == 0,
            )
        return self._answered(session, learner, register, answer, today, ending=ending)

    def _answered(  # noqa: PLR0913  # plus how the reply ends
        self,
        session: ChildSession,
        learner: Learner,
        register: Language,
        answer: _Answer,
        today: _Today,
        *,
        ending: ChildSessionEndReason | None,
        handover: bool = False,
    ) -> LayerResult:
        """The answer as one reply, counted as a question: then the goodbye and the parent's
        summary when the session ends with it (a limit, or the child going), or the "Yes, I'm
        the parent" button when a grown-up has the phone too (`handover`; owner, 2026-11-20)."""
        counted = ChildTalkTurn(session_id=session.id, topic=answer.topic)
        source = CuriositySource(
            learner_id=learner.id, kind="child_words", hint_domains=[], activity_title=None
        )
        if ending is None:
            reply = answer.text
            if handover:
                ask = ChildTalkLayer._takeover_ask(learner, register).reply
                reply = reply.model_copy(
                    update={
                        "body": f"{reply.body}\n\n{ask.body}",
                        "spoken_text": f"{reply.spoken_text} {ask.spoken_text}",
                        "buttons": ask.buttons,
                    }
                )
            return LayerResult(
                curiosity=source if answer.degraded_reason is None else None,
                reply=reply,
                usages=answer.usages,
                prompt_versions=answer.prompt_versions,
                outcome=StepOutcome.DEGRADED if answer.degraded_reason else StepOutcome.OK,
                degraded_reason=answer.degraded_reason,
                writes=[counted],
                hazard_rule=TALKABLE_HAZARDS,  # talked about, never done (d7)
            )
        new_topics = (answer.topic,) if answer.topic else ()
        goodbye = self._goodbye(
            session, learner, register, ending, today, new_topics=new_topics, answered_now=True
        )
        reply = answer.text.model_copy(
            update={
                "body": f"{answer.text.body}\n\n{goodbye.reply.body}",
                "spoken_text": f"{answer.text.spoken_text} {goodbye.reply.spoken_text}",
            }
        )
        return goodbye.model_copy(
            update={
                "reply": reply,
                "usages": answer.usages,
                "prompt_versions": answer.prompt_versions,
                "writes": [counted, *goodbye.writes],
                "curiosity": source if answer.degraded_reason is None else None,
                # a degraded last answer stays degraded with the goodbye after it
                "outcome": StepOutcome.DEGRADED if answer.degraded_reason else StepOutcome.OK,
                "degraded_reason": answer.degraded_reason,
                "hazard_rule": TALKABLE_HAZARDS,  # the last answer may still talk about one
            }
        )

    # --- the intent reading (owner, 2026-11-20) ----------------------------------------------

    async def _turn_as_read(
        self, turn: _SessionTurn, intents: ChildIntentReader, input_cleared: asyncio.Event
    ) -> LayerResult:
        """Words no rule decided, read for intent once safety_in has allowed them. The answer is
        written alongside the reading and used only if the words ask or tell something; when
        they might name a language, the answer waits for the reading, to be written once, in
        the language asked for. An unsure or failed reading: the rules' answer, as before."""
        if OnboardingAnswerParser.names_a_language(turn.text):
            read = await ChildTalkLayer._read(intents, turn, input_cleared)
            result = await self._act_on(read, turn, answering=None)
            return _with_child_reading(result, read)
        answering = asyncio.create_task(self._answer_for(turn, turn.register, turn.voice))
        try:
            read = await ChildTalkLayer._read(intents, turn, input_cleared)
            result = await self._act_on(read, turn, answering=answering)
        finally:
            await _discard_unused(answering)
        return _with_child_reading(result, read)

    @staticmethod
    async def _read(
        intents: ChildIntentReader, turn: _SessionTurn, input_cleared: asyncio.Event
    ) -> ChildIntentRead:
        await input_cleared.wait()  # never before safety_in's ALLOW (owner, 2026-11-20)
        return await intents.read(turn.text, turn.learner.nickname, turn.recent)

    async def _act_on(  # noqa: PLR0911  # one return per intent
        self,
        read: ChildIntentRead,
        turn: _SessionTurn,
        *,
        answering: "asyncio.Task[_Answer] | None",
    ) -> LayerResult:
        """What code does for each reading; the model never picks a route itself. `answering`:
        the answer already being written, in the turn's language; None: none started yet."""
        session, learner, register = turn.session, turn.learner, turn.register
        match read.intent:
            case ChildIntent.LEAVING:
                return self._goodbye(
                    session, learner, register, ChildSessionEndReason.CHILD_ENDED, turn.today
                )
            case ChildIntent.PARENT_HERE:
                return ChildTalkLayer._takeover_ask(learner, register)
            case ChildIntent.SMALL_TALK:
                return self._small_talk(turn)
            case ChildIntent.ACCOUNT_ACTION:
                return _fixed(ASK_A_GROWNUP, register)
            case ChildIntent.LANGUAGE_SWITCH if read.asked_language is not None:
                asked = ChildTalkLayer._asked_language(read.asked_language, turn.text)
                return ChildTalkLayer._language_switched(session, asked)
            case ChildIntent.TALK:
                return await self._talk(read, turn, answering)
            case _ if ChildSessionRules.names_the_child(turn.text, learner.nickname):
                # UNSURE or failed, on words the rule reads as a grown-up's ("Munni ne…")
                return ChildTalkLayer._takeover_ask(learner, register)
            case _:
                # UNSURE, or a failed reading: the rules already let it through, to be answered
                if answering is not None:
                    answer = await answering
                else:
                    answer = await self._answer_for(turn, register, turn.voice)
                ending = self._ending(session, daily_reached=turn.today.reached)
                return self._answered(session, learner, register, answer, turn.today, ending=ending)

    async def _talk(
        self,
        read: ChildIntentRead,
        turn: _SessionTurn,
        answering: "asyncio.Task[_Answer] | None",
    ) -> LayerResult:
        """The answer, once: in the language asked for, if any (then kept for the session, as
        a language asked for alone is). A session limit ends it as before; else the child going
        ends it, or a grown-up on the phone gets the button after it."""
        register, voice = turn.register, turn.voice
        writes: list[TurnWrite] = []
        if read.asked_language is not None:
            asked = ChildTalkLayer._asked_language(read.asked_language, turn.text)
            writes.append(ChildSessionLanguage(session_id=turn.session.id, language=asked))
            if answering is None:
                register, voice = asked, LocalVoice.for_turn(asked, turn.ctx, turn.text)
        ending = self._ending(turn.session, daily_reached=turn.today.reached)
        if ending is None and read.leaving_after:
            # the child is going: the answer in the last-answer style, then the goodbye; one
            # call (owner, 2026-11-20): the answer written alongside, its question removed in
            # code, or, written after the reading, asked for in the prompt (LAST_ANSWER_RULE)
            ending = ChildSessionEndReason.CHILD_ENDED
            if answering is not None:
                answer = (await answering).without_question(register)
            else:
                answer = await self._answer_for(turn, register, voice, last_answer=True)
        elif answering is not None:
            answer = await answering
        else:
            answer = await self._answer_for(turn, register, voice)
        answered = self._answered(
            turn.session,
            turn.learner,
            register,
            answer,
            turn.today,
            ending=ending,
            handover=read.handover_after,
        )
        return answered.model_copy(update={"writes": [*writes, *answered.writes]})

    async def _answer_for(
        self, turn: _SessionTurn, register: Language, voice: str, *, last_answer: bool = False
    ) -> _Answer:
        """`last_answer`: a goodbye follows for another reason than the limits (which set it
        themselves): nothing asked back (LAST_ANSWER_RULE)."""
        ending = self._ending(turn.session, daily_reached=turn.today.reached)
        return await self._answer(
            turn.learner,
            turn.text,
            turn.now,
            register,
            voice,
            last_answer=last_answer or ending is not None,
            first_answer=turn.session.turns_count == 0,
        )

    def _small_talk(self, turn: _SessionTurn) -> LayerResult:
        """Small talk the reading found: the rules' replies, never counted as a question
        (owner, 2026-11-20). With the day's time used up, the day's goodbye; a greeting in it
        ("namaste didi"), the hello; else the quick ok."""
        if turn.today.reached:
            return self._goodbye(
                turn.session,
                turn.learner,
                turn.register,
                ChildSessionEndReason.DAILY_LIMIT,
                turn.today,
            )
        if OnboardingAnswerParser.mentions_a_greeting(turn.text):
            return _fixed(CHILD_GREETED, turn.register)
        return ChildTalkLayer._acknowledged(turn.register, turn.previous_reply)

    @staticmethod
    def _asked_language(asked: Language, child_words: str) -> Language:
        """The script follows what was typed, as for a language named alone (owner,
        2026-10-29): Hindi asked for in Roman letters is Hinglish."""
        roman = (
            RegisterDetector.devanagari_share(child_words) or 0.0
        ) < RegisterDetector.DEVANAGARI_AT_MOST
        if asked is Language.HINDI and roman:
            return Language.HINGLISH
        return asked

    def _ending(
        self, session: ChildSession, *, daily_reached: bool
    ) -> ChildSessionEndReason | None:
        """Whether the answer this turn is the session's last, and why: the session's last
        allowed question, or the child's time for today used up (owner, 2026-11-13: the answer
        is completed, then the goodbye). None: the session goes on."""
        if ChildSessionRules.is_last_turn(session, self._limits):
            return ChildSessionEndReason.TURN_LIMIT
        if daily_reached:
            return ChildSessionEndReason.DAILY_LIMIT
        return None

    def _goodbye(  # noqa: PLR0913  # plus this turn's topic and whether it answered
        self,
        session: ChildSession,
        learner: Learner,
        register: Language,
        reason: ChildSessionEndReason,
        today: _Today,
        *,
        new_topics: Sequence[CuriosityDomain] = (),
        answered_now: bool = False,
    ) -> LayerResult:
        """The goodbye to the child (spoken), then the parent's summary (text only): the topics
        and the child's time today against their limit. No summary when the child asked
        nothing: "Munni talked with Marg" wouldn't be true (owner, 2026-10-29). When the day's
        time ran out, the goodbye says so: until tomorrow."""
        asked_something = session.turns_count > 0 or answered_now
        goodbye = (
            CHILD_DAILY_LIMIT_REACHED
            if reason is ChildSessionEndReason.DAILY_LIMIT
            else CHILD_GOODBYE
        )
        body = goodbye[register]
        if asked_something:
            summary = ChildTalkLayer.parent_summary(
                learner.nickname, [*session.topics, *new_topics], register, today.talk_time
            )
            body = f"{body}\n\n{summary}"
        return LayerResult(
            reply=CanonicalReply(
                body=body,
                body_language=register,
                spoken_text=goodbye[_voice_language(register)],
                citations=[],
                buttons=[],
                fixed_kind=None,
            ),
            usages=[],
            prompt_versions={},
            outcome=StepOutcome.OK,
            degraded_reason=None,
            writes=[ChildSessionEnd(session_id=session.id, reason=reason)],
            hazard_rule=frozenset(),
        )

    @staticmethod
    def _parent_took_over(
        session: ChildSession, learner: Learner, register: Language, talk_time: DailyTalkTime
    ) -> LayerResult:
        """ "Yes, I'm the parent": the child's session ends (recorded like a goodbye from the
        phone, CHILD_ENDED), and the parent gets the summary, topics and time; their next
        message is answered as theirs (owner, 2026-11-01)."""
        name = learner.nickname or UNNAMED_CHILD_NAME[register]
        body = PARENT_TAKEOVER_DONE[register].format(name=name)
        if session.turns_count > 0:
            summary = ChildTalkLayer.parent_summary(
                learner.nickname, session.topics, register, talk_time
            )
            body = f"{body}\n\n{summary}"
        ended = ChildSessionEnd(session_id=session.id, reason=ChildSessionEndReason.CHILD_ENDED)
        return LayerResult(
            reply=CanonicalReply(
                body=body,
                body_language=register,
                spoken_text=PARENT_TAKEOVER_DONE[_voice_language(register)].format(name=""),
                citations=[],
                buttons=[],
                fixed_kind=None,
            ),
            usages=[],
            prompt_versions={},
            outcome=StepOutcome.OK,
            degraded_reason=None,
            writes=[ended],
            hazard_rule=frozenset(),
        )

    async def _answer(  # noqa: PLR0913  # plus whether it's the session's last answer
        self,
        learner: Learner,
        user_text: str,
        now: datetime,
        register: Language,
        voice: str,
        *,
        last_answer: bool,
        first_answer: bool,
    ) -> _Answer:
        age = StageRules.age_on(learner.birth_year, now.date())
        band: Literal["young", "older"] = "young" if age <= YOUNGEST_BAND_MAX_AGE else "older"
        max_words = self.WORDS_PER_SENTENCE[band]
        rendered = self._registry.render(
            CHILD_TALK,
            system_vars={
                "language_rule": ParentQuestionLayer.LANGUAGE_RULES[register].replace(
                    "answer and try_this", "answer, find_out and ask_back"
                )
                + f" {voice}",
                "spoken_rule": ParentQuestionLayer.SPOKEN_RULES[register],
                "child_age": age,
                "max_words": max_words,
                "topics": ", ".join(domain.value for domain in CuriosityDomain),
                "closing_rule": ChildTalkLayer.LAST_ANSWER_RULE if last_answer else "",
            },
            user_vars={"child": learner.nickname or "", "child_message": user_text},
            semantic_check=lambda reply: _ChildChecks.problems(reply, register, max_words),
        )
        versions = {rendered.request.prompt.prompt_id: rendered.request.prompt.prompt_version}
        try:
            result = await self._llm.generate(rendered.request)
        except ProviderResponseInvalid:
            # Twice-failed checks: a redirect instead (owner, 2026-10-28), then fixed text
            redirect = await self._redirect(
                learner, user_text, now, register, voice=voice, reason="unanswered"
            )
            return _Answer(
                redirect.text,
                redirect.topic,
                redirect.usages,
                {**versions, **redirect.prompt_versions},
                redirect.degraded_reason or "child_redirect_after=ProviderResponseInvalid",
                redirect.child_reply,
            )
        # "Tell Mummy and Papa too" at the start and on feelings; the goodbye says it at the end
        remind = first_answer or result.output.topic is CuriosityDomain.PEOPLE_FEELINGS
        reply = _ChildText.reply(result.output, register, remind=remind and not last_answer)
        return _Answer(reply, result.output.topic, [result.usage], versions, None, result.output)

    async def _redirect(  # noqa: PLR0913  # the same inputs as an answer, plus the reason
        self,
        learner: Learner,
        user_text: str,
        now: datetime,
        register: Language,
        *,
        voice: str,
        reason: RedirectReason,
    ) -> _Answer:
        """What a kind elder says when they won't answer directly: why, gently, and something
        safe to wonder about instead. Fixed text if it fails its checks twice."""
        age = StageRules.age_on(learner.birth_year, now.date())
        band: Literal["young", "older"] = "young" if age <= YOUNGEST_BAND_MAX_AGE else "older"
        max_words = self.WORDS_PER_SENTENCE[band]
        rendered = self._registry.render(
            CHILD_REDIRECT,
            system_vars={
                "language_rule": ParentQuestionLayer.LANGUAGE_RULES[register].replace(
                    "answer and try_this", "answer, find_out and ask_back"
                )
                + f" {voice}",
                "spoken_rule": ParentQuestionLayer.SPOKEN_RULES[register],
                "child_age": age,
                "max_words": max_words,
                "reason": reason,
                "topics": ", ".join(domain.value for domain in CuriosityDomain),
            },
            user_vars={"child": learner.nickname or "", "child_message": user_text},
            semantic_check=lambda reply: _ChildChecks.problems(reply, register, max_words),
        )
        versions = {rendered.request.prompt.prompt_id: rendered.request.prompt.prompt_version}
        try:
            result = await self._llm.generate(rendered.request)
        except ProviderResponseInvalid:
            # Twice-failed checks: a kind fixed reply, never an unchecked one (DEGRADED)
            return _Answer(
                ChildTalkLayer._redirect_fallback(reason, register),
                None,
                [],
                versions,
                "child_fallback=ProviderResponseInvalid",
            )
        # a redirect is always about something sensitive: always "tell Mummy and Papa"
        reply = _ChildText.reply(result.output, register, remind=True)
        return _Answer(reply, result.output.topic, [result.usage], versions, None, result.output)

    @staticmethod
    def _redirect_fallback(reason: RedirectReason, register: Language) -> CanonicalReply:
        if reason == "unanswered":
            return _child_reply_text(CHILD_FALLBACK[register], None, register, remind=True)
        copy = {
            "hurting": CHILD_REFUSE_HURTING,
            "weapons": CHILD_REFUSE_DANGER,
            "rules": CHILD_REFUSE_OTHER,
        }[reason]
        voice = _voice_language(register)  # these already send the child to Mummy-Papa
        return CanonicalReply(
            body=copy[register],
            body_language=register,
            spoken_text=copy[voice],
            citations=[],
            buttons=[],
            fixed_kind=None,
        )

    @staticmethod
    def _reason(blocked: frozenset[SafetyCategory]) -> RedirectReason:
        reasons = {ChildTalkLayer.REDIRECT_REASONS[category] for category in blocked}
        for reason in ChildTalkLayer._REASON_ORDER:
            if reason in reasons:
                return reason
        raise ValueError("a redirect needs a category from REDIRECT_REASONS")

    @staticmethod
    def parent_summary(
        nickname: str | None,
        topics: Sequence[CuriosityDomain],
        register: Language,
        talk_time: DailyTalkTime,
    ) -> str:
        """What the child asked about, for the parent: reviewed wording and topic labels only,
        never the child's words; then the child's time that day against their daily limit
        (owner, 2026-11-13). Used at the goodbye, when the parent takes the phone back, and by
        maintenance for a session the child left without a goodbye. Never after a crisis."""
        topics_line = _ParentSummary.text(nickname, topics, register)
        return f"{topics_line}\n{_ParentSummary.time_line(talk_time, register)}"

    @staticmethod
    def _is_account_action(
        user_text: str, interactive_ids: Sequence[str], learner: Learner
    ) -> bool:
        """Anything that would change the account (C16): deletion, adding a child, the daily
        talk limit (the parent's alone; owner, 2026-11-13), or any button but `kid:`. A language
        request changes only the session (handled before)."""
        if any(not button.startswith(KID_START) for button in interactive_ids):
            return True
        return (
            OnboardingAnswerParser.asks_for_deletion(user_text)
            or OnboardingAnswerParser.asks_to_add_child(user_text)
            or ChildTalkLimitParser.is_about_the_limit(user_text, [learner])
        )


class _ChildText:
    @staticmethod
    def reply(child_reply: ChildReply, register: Language, *, remind: bool) -> CanonicalReply:
        parts = [child_reply.answer]
        if child_reply.find_out.strip():
            parts.append(child_reply.find_out)
        parts.append(child_reply.ask_back)
        if child_reply.who_explores_this.strip():
            parts.append(SentenceCase.of(child_reply.who_explores_this))
        return _child_reply_text(
            "\n\n".join(parts), child_reply.spoken_text, register, remind=remind
        )

    @staticmethod
    def last_answer(child_reply: ChildReply, register: Language) -> CanonicalReply:
        """The reply without its question back: `ask_back` left out of the text, and every
        sentence ending in "?" out of the spoken text (ask_back is the reply's only question:
        the child_talk prompt). No "tell Mummy and Papa": the goodbye after it says so."""
        parts = [child_reply.answer]
        if child_reply.find_out.strip():
            parts.append(child_reply.find_out)
        if child_reply.who_explores_this.strip():
            parts.append(SentenceCase.of(child_reply.who_explores_this))
        spoken = " ".join(
            sentence.strip()
            for sentence in ChildReplyMatcher.sentences(child_reply.spoken_text)
            if sentence.strip() and not sentence.strip().endswith("?")
        )
        return _child_reply_text("\n\n".join(parts), spoken, register, remind=False)


def _child_reply_text(
    body: str, spoken: str | None, register: Language, *, remind: bool
) -> CanonicalReply:
    """A reply to the child. "Tell Mummy and Papa too" is added by code when `remind` (the
    session's first answer, a feeling, a redirect, the fallback) and the reply doesn't already
    say it: on every reply it read as a parrot (owner, 2026-11-01)."""
    voice = _voice_language(register)
    spoken_body = spoken if spoken is not None else CHILD_FALLBACK[voice]
    if not remind or ParentMention.found(body):
        return CanonicalReply(
            body=body,
            body_language=register,
            spoken_text=spoken_body,
            citations=[],
            buttons=[],
            fixed_kind=None,
        )
    return CanonicalReply(
        body=f"{body}\n\n{TELL_YOUR_PARENTS[register]}",
        body_language=register,
        spoken_text=f"{spoken_body} {TELL_YOUR_PARENTS[voice]}",
        citations=[],
        buttons=[],
        fixed_kind=None,
    )


class _ParentSummary:
    @staticmethod
    def text(nickname: str | None, topics: Sequence[CuriosityDomain], register: Language) -> str:
        name = nickname or UNNAMED_CHILD_NAME[register]
        unique_topics = list(dict.fromkeys(topics))
        if not unique_topics:
            return PARENT_SUMMARY_NO_TOPICS[register].format(name=name)
        labels = [TOPIC_LABELS[topic][register] for topic in unique_topics]
        return PARENT_SUMMARY[register].format(name=name, topics=", ".join(labels))

    @staticmethod
    def time_line(talk_time: DailyTalkTime, register: Language) -> str:
        """ "⏱️ Aaj kul baat: 14 minute. Roz ki limit: 30 minute.", or the limit is used up,
        or there is none."""
        used = minutes_said(talk_time.used, register)
        if talk_time.limit is DailyTalkLimit.NO_LIMIT:
            return PARENT_TALK_TIME_NO_LIMIT[register].format(used=used)
        limit = DAILY_LIMIT_NAMES[talk_time.limit][register]
        if ChildDailyLimitRules.is_used_up(talk_time):
            return PARENT_TALK_TIME_USED_UP[register].format(used=used, limit=limit)
        return PARENT_TALK_TIME[register].format(used=used, limit=limit)


class _ChildChecks:
    """The semantic check: fixed-vocabulary problems for the one repair retry."""

    @staticmethod
    def problems(
        reply: ChildReply,
        register: Language,
        max_words: int,
    ) -> list[str]:
        written = [reply.answer, reply.find_out, reply.ask_back, reply.who_explores_this]
        joined = " ".join(written)
        problems: list[str] = []
        if _ChildChecks._longest_sentence(written) > max_words:
            problems.append(f"text: keep every sentence to at most {max_words} words")
        if ChildReplyMatcher.manipulates(
            f"{joined} {reply.spoken_text}", CHILD_MANIPULATION_PHRASES
        ):
            problems.append("text: talks about secrets or being the child's only friend")
        if ChildReplyMatcher.asks_personal_details(joined, QUESTION_WORDS, CHILD_PERSONAL_TOPICS):
            problems.append("text: asks the child for personal details")
        if ChildHazardMatcher.find(reply.find_out, CHILD_HAZARD_WORDS, CHILD_SAFE_TOOL_PHRASES):
            problems.append("find_out: nothing dangerous, even what the child asked about")
        talked_about = ChildHazardMatcher.find(f"{joined} {reply.spoken_text}", CHILD_HAZARD_WORDS)
        if talked_about & NEVER_TALK_ABOUT:
            problems.append("text: nothing about medicine; say to ask Mummy, Papa or a doctor")
        if ChildHazardMatcher.spoken_only(
            reply.spoken_text, joined, CHILD_HAZARD_WORDS, CHILD_SAFE_TOOL_PHRASES
        ):
            problems.append("spoken_text: names a danger the written text doesn't")
        if ActivityValidator.mentions_buying(written):
            problems.append("text: asks for something to be bought")
        if PhraseFinder.contains_any(joined, LABEL_WORDS):
            problems.append("text: labels the child")
        if PhraseFinder.contains_any(joined, CAREER_WORDS):
            problems.append("text: mentions careers, jobs or exams")
        if PhraseFinder.contains_any(reply.who_explores_this, EXPOSURE_PUSH_WORDS):
            problems.append("who_explores_this: tells the child to become something")
        problems.extend(RegisterDetector.script_problems(joined, reply.spoken_text, register))
        return problems

    @staticmethod
    def _longest_sentence(texts: Sequence[str]) -> int:
        longest = 0
        for text in texts:
            for sentence in ChildReplyMatcher.sentences(text):
                longest = max(longest, len(sentence.split()))
        return longest


def _fixed(
    copy: Mapping[Language, str],
    register: Language,
    buttons: Sequence[ReplyButton] = (),
    name: str = "",
) -> LayerResult:
    """Fixed child-talk copy. The spoken text comes from the voice's own language (Hindi for
    Hinglish) and leaves the nickname out: it may be in Roman letters the Hindi voice can't
    read."""
    return LayerResult(
        reply=CanonicalReply(
            body=copy[register].format(name=name),
            body_language=register,
            spoken_text=copy[_voice_language(register)].format(name=""),
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


async def _discard_unused(answering: "asyncio.Task[_Answer]") -> None:
    """The answer written alongside a reading that didn't need it (a goodbye, the parent's
    button…): cancelled and never read. An answer already used is left as it is."""
    answering.cancel()
    await asyncio.gather(answering, return_exceptions=True)


def _with_child_reading(result: LayerResult, read: ChildIntentRead) -> LayerResult:
    """The reading's usage and prompt version go with the turn's result. A failed reading (the
    rules decided) marks the turn DEGRADED; else the step's detail says what was read
    ("child_intent=talk+leaving_after")."""
    update: dict[str, object] = {
        "usages": [read.usage, *result.usages] if read.usage else result.usages,
        "prompt_versions": {**read.prompt_versions, **result.prompt_versions},
    }
    if read.failed is not None:
        if result.outcome is StepOutcome.OK:
            update |= {"outcome": StepOutcome.DEGRADED, "degraded_reason": read.failed}
    elif read.intent is not None and result.step_note is None:
        note = f"child_intent={read.intent.value}"
        if read.leaving_reason is not None:
            note += f":{read.leaving_reason.value}"
        if read.leaving_after:
            note += "+leaving_after"
        if read.handover_after:
            note += "+handover_after"
        update["step_note"] = note
    return result.model_copy(update=update)


def _voice_language(register: Language) -> Language:
    return Language.HINDI if register is Language.HINGLISH else register


def _learner(learners: Sequence[Learner], learner_id: UUID) -> Learner:
    for learner in learners:
        if learner.id == learner_id:
            return learner
    raise ValueError("an open child session always belongs to one of the parent's learners")
