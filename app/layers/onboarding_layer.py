"""OnboardingLayer: a message during onboarding → a state-machine event → fixed copy and writes
(s08 §4.4, §4.8, §4.9).

The layer writes nothing itself. It returns the reply, the `TurnWrite`s the worker commits with
the reply, and an optional handoff (the first khoj, or a remembered question). Deterministic rules
read the common answers; the ProfileExtraction model call reads the rest, and when it fails the
answer counts as not understood (outcome DEGRADED), never as a guess.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import ClassVar, Final, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from app.constants.lgd_districts import DISTRICTS
from app.constants.onboarding_copy import (
    ADD_CHILD,
    CHANNEL_VARIANTS,
    CHILD_FALLBACK,
    CHILD_TALK_NO,
    CHILD_TALK_YES,
    CONSENT_NO,
    CONSENT_YES,
    COPY,
    COPY_VERSION,
    DELETE_ASK,
    DELETE_NO,
    DELETE_YES,
    DISTRICT_BUTTON,
    DISTRICT_NO,
    DISTRICT_NO_TITLE,
    DISTRICT_NONE_TITLE,
    DISTRICT_YES_TITLE,
    GUARDIAN_NO,
    GUARDIAN_YES,
    ROLE_PARENT,
    ROLE_STUDENT,
    ROLE_TEACHER,
)
from app.core.errors import ConfigError, InvalidProfileValue, ProviderError
from app.domain.enums import (
    Channel,
    ConversationState,
    CopyKey,
    FixedReplyKind,
    Language,
    Role,
    StepOutcome,
)
from app.domain.models.conversation import (
    GRADUATE,
    STUDENT_LEVELS,
    AboutMargAsked,
    AddChild,
    ChildAnswered,
    ChildInvalid,
    ChildNamed,
    ChildrenAnswered,
    ChildTalkAnswered,
    ConsentDeclined,
    ConsentGiven,
    ConversationEvent,
    DeletionCancelled,
    DeletionConfirmed,
    DeletionRequested,
    DistrictUnclear,
    FirstContact,
    GuardianConfirmed,
    GuardianDeclined,
    HandoffFirstKhoj,
    HandoffPendingQuestion,
    LanguageSwitched,
    ProfileAnswered,
    ProfileUpdate,
    PurgeAfterDelivery,
    QuestionNoted,
    RecordConsent,
    RoleChosen,
    SendCopy,
    SetChildTalk,
    TeacherAsked,
    Transition,
    Unrecognised,
    UpsertLearner,
)
from app.domain.models.learner import Learner, LearnerId
from app.domain.models.reply import CanonicalReply, ReplyButton
from app.domain.models.turn import Exchange, TurnContext, UserProfile
from app.domain.models.usage import StepUsage
from app.domain.models.writes import (
    ChildTalkConsent,
    LearnerUpsert,
    MarkPurgeAfterDelivery,
    ProfileChange,
    TurnWrite,
)
from app.domain.rules.conversation_machine import ConversationMachine
from app.domain.rules.district_matcher import DistrictMatcher
from app.domain.rules.onboarding_answer_parser import ChildrenParse, Found, OnboardingAnswerParser
from app.domain.rules.register_detector import RegisterDetector
from app.layers.about_marg_layer import AboutMargLayer
from app.layers.layer_result import LayerResult
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel

_S = ConversationState
_P = OnboardingAnswerParser
QUESTION_MAX_CHARS: Final = 500


class ProfileExtraction(BaseModel):
    """What the extraction model read in an answer (strict schema: every field required)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["parent", "teacher", "student"] | None
    grade: int | None
    subject: str | None
    district: str | None
    child_age: int | None
    child_nickname: str | None
    language: Literal["english", "hindi", "hinglish"] | None
    question: str | None
    about_marg: bool  # the question is about Marg itself: answered at once (2026-11-01)


PROFILE_EXTRACTION: Final = PromptSpec(
    prompt_id="profile_extraction", output_type=ProfileExtraction
)


@dataclass(frozen=True, slots=True)
class FirstKhojHandoff:
    learner: Learner  # created in this turn; its LearnerUpsert comes first in the writes
    # The child-talk question (C13), sent after the khoj rather than before it, so the khoj
    # isn't buried under questions (owner's judge walkthrough, 2026-10-29). None: not asked.
    then_ask: CanonicalReply | None = None


@dataclass(frozen=True, slots=True)
class PendingQuestionHandoff:
    question: str


@dataclass(frozen=True, slots=True)
class OnboardingResult:
    reply: CanonicalReply
    writes: list[TurnWrite]
    handoff: FirstKhojHandoff | PendingQuestionHandoff | None
    usages: list[StepUsage]
    prompt_versions: dict[str, str]
    outcome: Literal[StepOutcome.OK, StepOutcome.DEGRADED]
    degraded_reason: str | None
    # More messages after `reply`: one per further child-talk question when several children
    # were added at once (critic review D3, 2026-11-01)
    follow_ups: tuple[CanonicalReply, ...] = ()
    # A question about Marg answered from the facts, sent before `reply` once safety_out allows
    # it; its fallback_reply is the fixed paragraph (2026-11-02)
    about_marg: LayerResult | None = None


@dataclass(frozen=True, slots=True)
class _Reading:
    """What a message meant, and what it cost to find out."""

    event: ConversationEvent
    usages: tuple[StepUsage, ...] = ()
    prompt_versions: tuple[tuple[str, str], ...] = ()
    degraded_reason: str | None = None


class OnboardingLayer:
    EXTRACTION_STATES: ClassVar[frozenset[ConversationState]] = frozenset(
        {_S.AWAITING_ROLE, _S.AWAITING_PROFILE, _S.AWAITING_CHILD}
    )
    CONSENT_NOTE_FRESH: ClassVar[timedelta] = timedelta(hours=24)
    CONSENT_QUESTIONS: ClassVar[tuple[str, ...]] = (
        "Kya aap sahmat hain?",
        "क्या आप सहमत हैं?",
        "Do you agree?",
    )
    LONG_ANSWER_WORDS: ClassVar[int] = 3  # longer than this may be a question: ask the model
    SHORT_VALUE_WORDS: ClassVar[int] = 3  # a subject or district answer is a few words
    _BUTTON_EVENTS: ClassVar[dict[str, ConversationEvent]] = {
        CONSENT_YES: ConsentGiven(),
        CONSENT_NO: ConsentDeclined(),
        ROLE_PARENT: RoleChosen(Role.PARENT),
        ROLE_TEACHER: RoleChosen(Role.TEACHER),
        ROLE_STUDENT: RoleChosen(Role.STUDENT),
        GUARDIAN_YES: GuardianConfirmed(),
        GUARDIAN_NO: GuardianDeclined(),
        DELETE_YES: DeletionConfirmed(),
        DELETE_NO: DeletionCancelled(),
        DELETE_ASK: DeletionRequested(),
        ADD_CHILD: AddChild(),
    }

    @staticmethod
    def check_copy() -> None:
        """Startup check: every copy key has text in every language. Raises ConfigError."""
        missing = [
            f"{key.value}/{language.value}"
            for key in CopyKey
            for language in Language
            if (key, language) not in COPY
        ]
        if missing:
            raise ConfigError(f"onboarding copy missing: {', '.join(missing)}")

    def __init__(
        self,
        llm: LanguageModel,
        registry: PromptRegistry,
        invite_link: str,
        *,
        web_default_language: Language | None = None,
    ) -> None:
        """`web_default_language`: WEB_DEFAULT_LANGUAGE, what a web visitor's greeting gets."""
        self._llm = llm
        self._registry = registry
        self._invite_link = invite_link
        self._web_default_language = web_default_language
        self._about_marg = AboutMargLayer(llm, registry)

    async def handle(
        self, ctx: TurnContext, user_text: str, interactive_ids: Sequence[str], now: datetime
    ) -> OnboardingResult:
        """Raises InvalidTransition or InvalidProfileValue only on a bug: the interpreter
        produces events the current state allows. A failed extraction call isn't raised: the
        answer counts as not understood, and the result says DEGRADED with the error's type."""
        reading = OnboardingLayer._consent_note_seen(
            ctx, await self._read(ctx, user_text, interactive_ids, now), now
        )
        transition = ConversationMachine.transition(
            ctx.profile, len(ctx.learners), reading.event, now
        )
        result = self._result(ctx, reading, transition)
        if isinstance(reading.event, AboutMargAsked) and not reading.event.braj:
            return await self._with_facts_answer(ctx, user_text, transition, result)
        return result

    async def _with_facts_answer(
        self,
        ctx: TurnContext,
        user_text: str,
        transition: Transition,
        result: OnboardingResult,
    ) -> OnboardingResult:
        """A question about Marg is answered from the reviewed facts, as after onboarding, then
        the waiting question (owner, 2026-11-02: one behaviour, every persona). The fixed
        paragraph is the answer's fallback, and the answer itself if the model can't reply."""
        # the account's language, like the waiting question after it: one reply, one language
        language = transition.profile.language or Language.HINGLISH
        try:
            answer = await self._about_marg.answer(ctx, user_text, language)
        except ProviderError as exc:
            degraded = f"about_marg_failed={type(exc).__name__}"
            return replace(result, outcome=StepOutcome.DEGRADED, degraded_reason=degraded)
        paragraph = self._reply(
            [_Copy(CopyKey.ABOUT_MARG, None, None)], language, FixedReplyKind.ONBOARDING
        )
        waiting = ConversationMachine.question_for(transition.profile, len(ctx.learners))
        question_only = [_Copy(waiting, None, None)] if waiting else []
        return replace(
            result,
            reply=self._reply(question_only, language, FixedReplyKind.ONBOARDING),
            about_marg=answer.model_copy(update={"fallback_reply": paragraph}),
            usages=[*result.usages, *answer.usages],
            prompt_versions={**result.prompt_versions, **answer.prompt_versions},
        )

    @staticmethod
    def _consent_note_seen(ctx: TurnContext, reading: _Reading, now: datetime) -> _Reading:
        """Before consent, an answer that isn't yes or no points to the note, if Marg sent it
        within CONSENT_NOTE_FRESH; after that, the note is sent again in full."""
        event = reading.event
        if ctx.profile.state is not _S.AWAITING_CONSENT or not isinstance(event, Unrecognised):
            return reading
        if not OnboardingLayer.consent_note_sent_since(
            ctx.recent_exchanges, now - OnboardingLayer.CONSENT_NOTE_FRESH
        ):
            return reading
        return replace(reading, event=replace(event, consent_note_shown=True))

    @staticmethod
    def consent_note_sent_since(exchanges: Sequence[Exchange], since: datetime) -> bool:
        """A reply after `since` held the note: it ends with the consent question, in every
        language."""
        for exchange in exchanges:
            held_the_note = any(
                question in exchange.reply_text for question in OnboardingLayer.CONSENT_QUESTIONS
            )
            if held_the_note and exchange.at >= since:
                return True
        return False

    # --- reading a message -----------------------------------------------------------------------

    async def _read(
        self,
        ctx: TurnContext,
        user_text: str,
        interactive_ids: Sequence[str],
        now: datetime,
    ) -> _Reading:
        profile = ctx.profile
        allowed = ConversationMachine.allowed_events(profile.state, profile.role)
        event = self._deterministic(ctx, user_text, interactive_ids, now)
        waiting = profile.state is not _S.ACTIVE
        if event is None and waiting and user_text.strip() and _P.is_greeting(user_text):
            return _Reading(Unrecognised(greeted=True))
        if event is None and self._worth_extracting(profile.state, user_text):
            return await self._extract(ctx, user_text, now, allowed)
        if event is None or type(event) not in allowed:
            return _Reading(Unrecognised())
        return _Reading(event)

    def _deterministic(  # one return per rule, in s08 §4.4's order
        self,
        ctx: TurnContext,
        user_text: str,
        interactive_ids: Sequence[str],
        now: datetime,
    ) -> ConversationEvent | None:
        profile = ctx.profile
        if interactive_ids:
            return self._button_event(ctx, interactive_ids[-1])
        if _P.asks_for_deletion(user_text):
            return DeletionRequested()
        if profile.state is _S.NEW:
            return self._first_contact(user_text, profile.channel)
        about_language = self._language_event(ctx, user_text)
        if about_language is not None:
            return about_language
        if profile.state is _S.ACTIVE:
            return self._active_event(ctx, user_text, now.year)
        return self._answer_event(ctx, user_text, now)

    def _language_event(self, ctx: TurnContext, user_text: str) -> ConversationEvent | None:
        """A language named to switch to, or, before onboarding ends, a question whether Marg
        speaks Braj (owner's field test, 2026-11-01)."""
        if ctx.profile.state is not _S.ACTIVE and _P.asks_about_braj(user_text):
            return AboutMargAsked(braj=True)
        language = _P.language_named(user_text)
        if language is not None and not self._asks_subject(ctx):
            # "Hindi" answering "which subject do you teach?" is a subject, not a switch.
            return LanguageSwitched(language)
        return None

    def _first_contact(self, user_text: str, channel: Channel) -> FirstContact:
        """A greeting says nothing about the language unless it's in Devanagari ("Namaste" is
        typed by Hinglish and English speakers alike): the default then applies. On WhatsApp
        that is Hinglish (the families Marg serves); on the web demo, WEB_DEFAULT_LANGUAGE
        (English, for judges and visitors; owner, 2026-10-29)."""
        requested = _P.language_requested(user_text)
        if requested is not None:
            return FirstContact(requested, None)
        detected = RegisterDetector.detect(user_text)
        if _P.is_greeting(user_text) or _P.is_acknowledgement(user_text):
            if detected is Language.HINDI:
                return FirstContact(Language.HINDI, None)
            web_default = self._web_default_language if channel is Channel.WEB else None
            return FirstContact(web_default, None)
        return FirstContact(detected, user_text[:QUESTION_MAX_CHARS])

    @staticmethod
    def _asks_subject(ctx: TurnContext) -> bool:
        asked = ConversationMachine.next_profile_question(ctx.profile, len(ctx.learners))
        return ctx.profile.state is _S.AWAITING_PROFILE and asked is CopyKey.ASK_SUBJECT_TEACHER

    def _button_event(self, ctx: TurnContext, button_id: str) -> ConversationEvent:
        event = self._BUTTON_EVENTS.get(button_id)
        if event is not None:
            return event
        if button_id.startswith(f"{DISTRICT_BUTTON}:"):
            return _DistrictReader.button(ctx, button_id)
        for prefix, allowed in ((CHILD_TALK_YES, True), (CHILD_TALK_NO, False)):
            learner_id = self._learner_in(ctx, button_id.removeprefix(f"{prefix}:"))
            if button_id.startswith(f"{prefix}:") and learner_id is not None:
                return ChildTalkAnswered(learner_id, allowed=allowed)
        return Unrecognised()  # an old or unknown onb: button

    @staticmethod
    def _learner_in(ctx: TurnContext, raw_id: str) -> LearnerId | None:
        """The learner a button names, only if it belongs to this user."""
        for learner in ctx.learners:
            if str(learner.id) == raw_id:
                return learner.id
        return None

    @staticmethod
    def _active_event(
        ctx: TurnContext, user_text: str, current_year: int
    ) -> ConversationEvent | None:
        role = ctx.profile.role
        if role is Role.TEACHER:
            return TeacherAsked()
        if role is Role.PARENT and _P.asks_to_add_child(user_text):
            return AddChild(OnboardingLayer._child_given_with(ctx, user_text, current_year))
        return None

    @staticmethod
    def _child_given_with(
        ctx: TurnContext, user_text: str, current_year: int
    ) -> ChildAnswered | ChildrenAnswered | None:
        """The child in "another child, Riya 7", or None to ask for it as the button does (an
        age out of range is asked again there too)."""
        if not _P.adds_a_child_with_age(user_text):
            return None
        answer = _P.without_new_child_phrase(user_text)
        match OnboardingLayer._child_event(ctx, answer, current_year):
            case ChildAnswered() | ChildrenAnswered() as given:
                return given
            case _:
                return None

    def _answer_event(  # one return per state's answer
        self, ctx: TurnContext, user_text: str, now: datetime
    ) -> ConversationEvent | None:
        state = ctx.profile.state
        if state in {_S.AWAITING_CONSENT, _S.AWAITING_GUARDIAN, _S.AWAITING_DELETION_CONFIRM}:
            said = _P.yes_or_no(user_text)
            if said is None:
                return None
            return _YES_NO_EVENTS[state][said]
        if state is _S.AWAITING_ROLE:
            role = _P.role_named(user_text)
            return RoleChosen(role) if role else None
        if state is _S.AWAITING_CHILD:
            return self._child_event(ctx, user_text, now.year)
        if state is _S.AWAITING_PROFILE:
            return self._profile_event(ctx, user_text)
        return None

    @staticmethod
    def _child_event(
        ctx: TurnContext, user_text: str, current_year: int
    ) -> ConversationEvent | None:
        several = _P.parse_children(user_text, current_year)
        if several is not None:
            return OnboardingLayer._children_event(several)
        age = _P.parse_child_age(user_text, current_year)
        if age.problem is Found.OUT_OF_RANGE:
            return ChildInvalid(CopyKey.CHILD_INVALID_AGE)
        if age.birth_year is None:
            return _ChildName.alone(user_text)
        nickname = _P.parse_nickname(user_text)
        if nickname.problem in {Found.TOO_LONG, Found.LOOKS_LIKE_FULL_NAME}:
            return ChildInvalid(CopyKey.CHILD_NICKNAME_TOO_LONG)
        if nickname.nickname is not None and len(nickname.nickname.split()) > 1:
            # "ghar mein Lala bolte hain" left "mein Lala bolte hain": not sure which word is
            # the name, so the extraction model reads it (onboarding bank, 2026-11-01)
            return None
        return ChildAnswered(age.birth_year, nickname.nickname or _ChildName.given_before(ctx))

    @staticmethod
    def _children_event(several: ChildrenParse) -> ConversationEvent:
        """ "Munni 5 aur Golu 7": both added (critic review D3, 2026-11-01)."""
        if several.problem is Found.OUT_OF_RANGE:
            return ChildInvalid(CopyKey.CHILD_INVALID_AGE)
        if several.problem is not None:
            return ChildInvalid(CopyKey.CHILD_NICKNAME_TOO_LONG)
        return ChildrenAnswered(
            tuple(ChildAnswered(child.birth_year, child.nickname) for child in several.children)
        )

    def _profile_event(self, ctx: TurnContext, user_text: str) -> ConversationEvent | None:
        asked = ConversationMachine.next_profile_question(ctx.profile, len(ctx.learners))
        if asked in {CopyKey.ASK_GRADE_STUDENT, CopyKey.ASK_GRADE_TEACHER}:
            return self._grade_event(user_text, student=asked is CopyKey.ASK_GRADE_STUDENT)
        is_short_value = (
            0 < len(user_text.split()) <= self.SHORT_VALUE_WORDS
            and "?" not in user_text
            and _P.yes_or_no(user_text) is None  # "pata nahi" is not a district
        )
        try:
            if asked is CopyKey.ASK_SUBJECT_TEACHER and is_short_value:
                return ProfileAnswered(ProfileUpdate(subject=user_text))
            if asked is CopyKey.ASK_DISTRICT and is_short_value:
                return _DistrictReader.typed(ctx, user_text)
        except InvalidProfileValue:
            return Unrecognised()  # malformed ("12345" as a district): ask again, store nothing
        return None

    def _grade_event(self, user_text: str, *, student: bool) -> ConversationEvent | None:
        """The class, from a short answer. A longer message may also carry a question or a
        teacher's chapter ("kal class 8 mein bal aur dabav padhana hai"): the model reads both,
        so the request isn't lost (owner, 2026-10-31). A student past class 12 ("mai graduate
        hun") is GRADUATE (owner's field test, 2026-11-01)."""
        words = len(user_text.split())
        short_graduate = words <= _P.SHORT_ANSWER_WORDS and "?" not in user_text
        if student and short_graduate and _P.is_graduate(user_text):
            return ProfileAnswered(ProfileUpdate(grade=GRADUATE))
        short_range = words <= _P.SHORT_ANSWER_WORDS and _P.names_a_class_range(user_text)
        if words > self.LONG_ANSWER_WORDS and not short_range:
            return None
        grade = _P.parse_grade(user_text)
        if grade.problem is Found.OUT_OF_RANGE:
            return Unrecognised(not_understood=CopyKey.INVALID_GRADE)
        return ProfileAnswered(ProfileUpdate(grade=grade.grade)) if grade.grade else None

    def _worth_extracting(self, state: ConversationState, user_text: str) -> bool:
        if state in {_S.NEW, _S.ACTIVE} or not user_text.strip():
            return False
        long_answer = len(user_text.split()) > self.LONG_ANSWER_WORDS
        return state in self.EXTRACTION_STATES or long_answer

    async def _extract(
        self,
        ctx: TurnContext,
        user_text: str,
        now: datetime,
        allowed: frozenset[type[ConversationEvent]],
    ) -> _Reading:
        asked = ConversationMachine.question_for(ctx.profile, len(ctx.learners))
        language = ctx.profile.language or Language.HINGLISH
        asked_text = COPY[(asked, language)].body if asked else "nothing specific"
        rendered = self._registry.render(
            PROFILE_EXTRACTION,
            system_vars={"asked": asked_text},
            user_vars={"user_message": user_text},
        )
        versions = ((rendered.request.prompt.prompt_id, rendered.request.prompt.prompt_version),)
        try:
            result = await self._llm.generate(rendered.request)
        except ProviderError as exc:
            return _Reading(
                Unrecognised(),
                prompt_versions=versions,
                degraded_reason=f"extraction_failed={type(exc).__name__}",
            )
        event = _ExtractionMapper.event_for(ctx, result.output, now.year)
        if event is None or type(event) not in allowed:
            event = Unrecognised()
        return _Reading(event, (result.usage,), versions)

    # --- building the result ---------------------------------------------------------------------

    def _result(
        self, ctx: TurnContext, reading: _Reading, transition: Transition
    ) -> OnboardingResult:
        writes: list[TurnWrite] = [_profile_change(ctx.profile, transition)]
        new_learner: Learner | None = None
        handoff: FirstKhojHandoff | PendingQuestionHandoff | None = None
        copies: list[_Copy] = []
        # a name given alone is said back in the age question (field test, 2026-11-01)
        child_named = reading.event.nickname if isinstance(reading.event, ChildNamed) else None
        for effect in transition.effects:
            match effect:
                case SendCopy(key=key):
                    copies.append(_Copy(key, child_named, new_learner))
                case UpsertLearner():
                    new_learner = Learner(
                        id=LearnerId(uuid4()),
                        relation=effect.relation,
                        nickname=effect.nickname,
                        birth_year=effect.birth_year,
                        child_talk_consented_at=None,
                    )
                    child_named = new_learner.nickname
                    writes.append(
                        LearnerUpsert(
                            learner_id=new_learner.id,
                            relation=new_learner.relation,
                            nickname=new_learner.nickname,
                            birth_year=new_learner.birth_year,
                        )
                    )
                case SetChildTalk(learner_id=learner_id, granted=granted):
                    writes.append(ChildTalkConsent(learner_id=learner_id, granted=granted))
                    child_named = _nickname_of(ctx.learners, learner_id)
                case PurgeAfterDelivery():
                    writes.append(MarkPurgeAfterDelivery())
                case HandoffFirstKhoj():
                    if new_learner is None:
                        raise InvalidProfileValue("a first-khoj handoff needs the new learner")
                    handoff = FirstKhojHandoff(new_learner)
                case HandoffPendingQuestion(question=question):
                    handoff = PendingQuestionHandoff(question)
                case RecordConsent():
                    pass  # carried by the ProfileChange (consent_events)
        fixed_kind = _fixed_kind([copy.key for copy in copies])
        language = transition.profile.language or Language.HINGLISH
        shown = [
            _Copy(
                CHANNEL_VARIANTS.get((copy.key, ctx.profile.channel), copy.key),
                copy.child,
                copy.learner,
            )
            for copy in copies
        ]
        if isinstance(handoff, FirstKhojHandoff):
            asks = [copy for copy in shown if copy.key is CopyKey.ASK_CHILD_TALK]
            if asks:
                shown.remove(asks[0])
                child_talk_question = self._reply([asks[0]], language, fixed_kind)
                handoff = FirstKhojHandoff(handoff.learner, then_ask=child_talk_question)
        messages = _OneQuestionEach.split(shown)
        district = reading.event if isinstance(reading.event, DistrictUnclear) else None
        replies = [self._reply(message, language, fixed_kind, district) for message in messages]
        return OnboardingResult(
            reply=replies[0] if replies else self._reply([], language, fixed_kind),
            writes=writes,
            handoff=handoff,
            usages=list(reading.usages),
            prompt_versions=dict(reading.prompt_versions),
            outcome=StepOutcome.DEGRADED if reading.degraded_reason else StepOutcome.OK,
            degraded_reason=reading.degraded_reason,
            follow_ups=tuple(replies[1:]),
        )

    def _reply(
        self,
        copies: Sequence["_Copy"],
        language: Language,
        fixed_kind: FixedReplyKind,
        district: DistrictUnclear | None = None,
    ) -> CanonicalReply:
        bodies: list[str] = []
        buttons: tuple[ReplyButton, ...] = ()
        for copy in copies:
            values = {
                "child": copy.child or CHILD_FALLBACK[language],
                "invite_link": self._invite_link,
                **_DistrictReader.values(district),
            }
            entry = COPY[(copy.key, language)]
            bodies.append(entry.body.format_map(values))
            if entry.buttons:
                buttons = entry.buttons
                if copy.key is CopyKey.ASK_CHILD_TALK and copy.learner is not None:
                    learner_id = copy.learner.id
                    buttons = tuple(
                        ReplyButton(id=f"{button.id}:{learner_id}", title=button.title)
                        for button in entry.buttons
                    )
            if district is not None and copy.key in _DistrictReader.CONFIRM_KEYS:
                buttons = _DistrictReader.buttons(district, language)
        return CanonicalReply(
            body="\n\n".join(bodies),
            body_language=language,
            spoken_text=None,
            citations=[],
            buttons=list(buttons),
            fixed_kind=fixed_kind,
        )


class _DistrictReader:
    """A district answer checked against LGD's list (critic review D4, owner 2026-11-01): an
    exact name is stored as "Karauli, Rajasthan"; anything less sure is confirmed or asked again
    once; a second unclear answer is stored as typed (unverified: not an LGD label)."""

    CONFIRM_KEYS: ClassVar[frozenset[CopyKey]] = frozenset(
        {CopyKey.DISTRICT_CONFIRM_ONE, CopyKey.DISTRICT_CONFIRM_MANY}
    )
    ASKED_KEYS: ClassVar[frozenset[CopyKey]] = CONFIRM_KEYS | {
        CopyKey.DISTRICT_WHICH_IN_STATE,
        CopyKey.DISTRICT_NOT_FOUND,
    }
    BUTTON_TITLE_MAX: ClassVar[int] = 20  # WhatsApp's limit

    @staticmethod
    def typed(ctx: TurnContext, typed: str) -> ConversationEvent:
        match = DistrictMatcher.match(typed, DISTRICTS)
        if match.found is not None:
            return ProfileAnswered(ProfileUpdate(district=match.found.label))
        if _DistrictReader._asked_before(ctx) and not match.candidates:
            # the way out (owner, 2026-11-01): asked once already, so keep what they wrote
            try:
                return ProfileAnswered(ProfileUpdate(district=typed.strip()))
            except InvalidProfileValue:
                return DistrictUnclear(())
        return DistrictUnclear(match.candidates, match.state_named)

    @staticmethod
    def button(ctx: TurnContext, button_id: str) -> ConversationEvent:
        asked = ConversationMachine.next_profile_question(ctx.profile, len(ctx.learners))
        if ctx.profile.state is not _S.AWAITING_PROFILE or asked is not CopyKey.ASK_DISTRICT:
            return Unrecognised()  # an old button
        if button_id == DISTRICT_NO:
            return DistrictUnclear(())
        district = _DISTRICTS_BY_CODE.get(button_id.removeprefix(f"{DISTRICT_BUTTON}:"))
        if district is None:
            return Unrecognised()
        return ProfileAnswered(ProfileUpdate(district=district.label))

    @staticmethod
    def values(district: DistrictUnclear | None) -> dict[str, str]:
        if district is None:
            return {}
        labels = [candidate.label for candidate in district.candidates]
        numbered = [f"{number}. {label}" for number, label in enumerate(labels, start=1)]
        return {
            "district": labels[0] if labels else "",
            "choices": "\n".join(numbered),
            "state": district.state_named or "",
        }

    @staticmethod
    def buttons(district: DistrictUnclear, language: Language) -> tuple[ReplyButton, ...]:
        candidates = district.candidates
        if len(candidates) == 1:
            return (
                ReplyButton(
                    id=f"{DISTRICT_BUTTON}:{candidates[0].code}",
                    title=DISTRICT_YES_TITLE[language],
                ),
                ReplyButton(id=DISTRICT_NO, title=DISTRICT_NO_TITLE[language]),
            )
        named = [
            ReplyButton(
                id=f"{DISTRICT_BUTTON}:{candidate.code}",
                title=candidate.name[: _DistrictReader.BUTTON_TITLE_MAX],
            )
            for candidate in candidates
        ]
        if len(named) < DistrictMatcher.MAX_CANDIDATES:
            named.append(ReplyButton(id=DISTRICT_NO, title=DISTRICT_NONE_TITLE[language]))
        return tuple(named)

    @staticmethod
    def _asked_before(ctx: TurnContext) -> bool:
        """Marg's last reply was one of the district questions: this is the second try."""
        if not ctx.recent_exchanges:
            return False
        last_reply = ctx.recent_exchanges[-1].reply_text
        for (key, _language), entry in COPY.items():
            if key not in _DistrictReader.ASKED_KEYS:
                continue
            fixed_parts = (part.strip() for part in _PLACEHOLDER.split(entry.body))
            longest = max(fixed_parts, key=len)
            if longest and longest in last_reply:
                return True
        return False


_PLACEHOLDER: Final = re.compile(r"\{\w+\}")
_DISTRICTS_BY_CODE: Final = {str(district.code): district for district in DISTRICTS}


@dataclass(frozen=True, slots=True)
class _Copy:
    """One piece of reviewed copy, and the child it is about (its name and, for the child-talk
    question, the learner its buttons answer for)."""

    key: CopyKey
    child: str | None
    learner: Learner | None


class _OneQuestionEach:
    """Copy split into messages so that each child-talk question ends its own message, with its
    own buttons (critic review D3, 2026-11-01: "Munni 5 aur Golu 7" asks about each child)."""

    @staticmethod
    def split(copies: Sequence[_Copy]) -> list[list[_Copy]]:
        messages: list[list[_Copy]] = []
        current: list[_Copy] = []
        for copy in copies:
            current.append(copy)
            if copy.key is CopyKey.ASK_CHILD_TALK:
                messages.append(current)
                current = []
        if current and messages:
            messages[-1] += current
        elif current:
            messages.append(current)
        return messages


class _ExtractionMapper:
    """ProfileExtraction → the event the current state can use (s08 §4.4 step 5)."""

    @staticmethod
    def event_for(  # one return per state's use of the extraction
        ctx: TurnContext, extraction: ProfileExtraction, current_year: int
    ) -> ConversationEvent | None:
        state = ctx.profile.state
        if extraction.language is not None:
            return LanguageSwitched(_EXTRACTED_LANGUAGES[extraction.language])
        if state is _S.AWAITING_ROLE and extraction.role is not None:
            return RoleChosen(Role(extraction.role))
        if state is _S.AWAITING_PROFILE:
            answered = _ExtractionMapper._profile_answer(ctx, extraction)
            if answered is not None:
                return answered
        if state is _S.AWAITING_CHILD:
            answered = _ExtractionMapper._child_answer(ctx, extraction, current_year)
            if answered is not None:
                return answered
        if extraction.question:
            # about Marg itself: answered at once; anything else: kept for after (2026-11-01)
            noted = QuestionNoted(extraction.question[:QUESTION_MAX_CHARS])
            return AboutMargAsked() if extraction.about_marg else noted
        return None

    @staticmethod
    def _profile_answer(
        ctx: TurnContext, extraction: ProfileExtraction
    ) -> ConversationEvent | None:
        """The profile fields read, or a district to check on its own (D4)."""
        update = _ExtractionMapper._profile_update(extraction, ctx.profile.role)
        if update is not None and not update.is_empty:
            question = extraction.question[:QUESTION_MAX_CHARS] if extraction.question else None
            return ProfileAnswered(update, question=question)
        if extraction.district:
            return _DistrictReader.typed(ctx, extraction.district)
        return None

    @staticmethod
    def _profile_update(extraction: ProfileExtraction, role: Role | None) -> ProfileUpdate | None:
        """Out-of-range or malformed values count as absent, never as the nearest valid one. A
        district counts only when LGD's list names it exactly; otherwise it's asked on its own.
        GRADUATE only for a student."""
        grades = STUDENT_LEVELS if role is Role.STUDENT else OnboardingAnswerParser.GRADES
        grade = extraction.grade if extraction.grade in grades else None
        district = None
        if extraction.district:
            found = DistrictMatcher.match(extraction.district, DISTRICTS).found
            district = found.label if found is not None else None
        try:
            return ProfileUpdate(grade=grade, subject=extraction.subject, district=district)
        except InvalidProfileValue:
            return None

    @staticmethod
    def _child_answer(
        ctx: TurnContext, extraction: ProfileExtraction, current_year: int
    ) -> ConversationEvent | None:
        """An age (with or without a name), or a name alone to ask the age for."""
        if extraction.child_age is not None:
            return _ExtractionMapper._child(ctx, extraction, current_year)
        if extraction.child_nickname and not extraction.question:
            return _ChildName.alone(extraction.child_nickname)
        return None

    @staticmethod
    def _child(
        ctx: TurnContext, extraction: ProfileExtraction, current_year: int
    ) -> ConversationEvent:
        age = extraction.child_age
        if age is None or age not in OnboardingAnswerParser.CHILD_AGES:
            return ChildInvalid(CopyKey.CHILD_INVALID_AGE)
        nickname = extraction.child_nickname
        if nickname is not None:
            parsed = OnboardingAnswerParser.parse_nickname(nickname)
            if parsed.nickname is None:
                return ChildInvalid(CopyKey.CHILD_NICKNAME_TOO_LONG)
            nickname = parsed.nickname
        return ChildAnswered(current_year - age, nickname or _ChildName.given_before(ctx))


class _ChildName:
    """A child's home name given without the age, and found again when the age comes next
    (owner's field test, 2026-11-01: "pinku hai naam" got "samajh nahi aaya" three times, and
    then "4 saal" added a child with no name)."""

    MAX_WORDS: ClassVar[int] = 3
    NOT_NAMES: ClassVar[frozenset[str]] = frozenset(
        {"kya", "kyu", "kyun", "kaise", "kaun", "kab", "kahan", "what", "why", "how", "who", "when"}
    )

    @staticmethod
    def alone(text: str) -> ChildNamed | None:
        """ "pinku", "pinku hai naam", "Guddu": one home name and nothing else."""
        words = text.split()
        if not words or len(words) > _ChildName.MAX_WORDS or "?" in text:
            return None
        said = {word.casefold() for word in words}
        if (
            said & _ChildName.NOT_NAMES
            or _P.yes_or_no(text) is not None
            or _P.is_acknowledgement(text)
            or _P.is_greeting(text)
        ):
            return None
        parsed = _P.parse_nickname(text)
        if parsed.nickname is None or len(parsed.nickname.split()) > 1:
            return None
        return ChildNamed(parsed.nickname)

    @staticmethod
    def given_before(ctx: TurnContext) -> str | None:
        """The name from the message before, when Marg's reply to it asked that child's age."""
        if not ctx.recent_exchanges:
            return None
        last = ctx.recent_exchanges[-1]
        for language in Language:
            asked = COPY[(CopyKey.ASK_CHILD_AGE, language)].body
            fixed_parts = (part.strip() for part in _PLACEHOLDER.split(asked))
            longest = max(fixed_parts, key=len)
            if longest and longest in last.reply_text:
                named = _ChildName.alone(last.user_text)
                return named.nickname if named is not None else None
        return None


_YES_NO_EVENTS: Final[dict[ConversationState, dict[bool, ConversationEvent]]] = {
    _S.AWAITING_CONSENT: {True: ConsentGiven(), False: ConsentDeclined()},
    _S.AWAITING_GUARDIAN: {True: GuardianConfirmed(), False: GuardianDeclined()},
    _S.AWAITING_DELETION_CONFIRM: {True: DeletionConfirmed(), False: DeletionCancelled()},
}
_EXTRACTED_LANGUAGES: Final = {
    "english": Language.ENGLISH,
    "hindi": Language.HINDI,
    "hinglish": Language.HINGLISH,
}


def _fixed_kind(keys: Sequence[CopyKey]) -> FixedReplyKind:
    if CopyKey.CONSENT_DECLINED in keys:
        return FixedReplyKind.CONSENT_DECLINED
    if CopyKey.DATA_DELETED in keys:
        return FixedReplyKind.DATA_DELETED
    return FixedReplyKind.ONBOARDING


def _profile_change(before: UserProfile, transition: Transition) -> ProfileChange:
    """The fields the transition changed (None = unchanged) and the consent events it recorded."""
    after = transition.profile
    consents = [effect.kind for effect in transition.effects if isinstance(effect, RecordConsent)]

    def changed[ValueT](old: ValueT | None, new: ValueT | None) -> ValueT | None:
        return new if new != old else None

    return ProfileChange(
        expected_state=before.state,
        new_state=after.state,
        role=changed(before.role, after.role),
        grade=changed(before.grade, after.grade),
        subject=changed(before.subject, after.subject),
        district=changed(before.district, after.district),
        language=changed(before.language, after.language),
        guardian_confirmed=changed(before.guardian_confirmed, after.guardian_confirmed),
        consented_at=changed(before.consented_at, after.consented_at),
        pending_question=changed(before.pending_question, after.pending_question),
        clear_pending_question=bool(before.pending_question) and after.pending_question is None,
        consent_events=consents,
        consent_prompt_version=COPY_VERSION if consents else None,
    )


def _nickname_of(learners: Sequence[Learner], learner_id: UUID) -> str | None:
    for learner in learners:
        if learner.id == learner_id:
            return learner.nickname
    return None
