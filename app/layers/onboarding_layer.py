"""OnboardingLayer: a message during onboarding → a state-machine event → fixed copy and writes
(s08 §4.4, §4.8, §4.9).

The layer writes nothing itself. It returns the reply, the `TurnWrite`s the worker commits with
the reply, and an optional handoff (the first khoj, or a remembered question). Deterministic rules
read the common answers; the ProfileExtraction model call reads the rest, and when it fails the
answer counts as not understood (outcome DEGRADED), never as a guess.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Final, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

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
    DELETE_NO,
    DELETE_YES,
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
    AddChild,
    ChildAnswered,
    ChildInvalid,
    ChildTalkAnswered,
    ConsentDeclined,
    ConsentGiven,
    ConversationEvent,
    DeletionCancelled,
    DeletionConfirmed,
    DeletionRequested,
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
from app.domain.models.turn import TurnContext, UserProfile
from app.domain.models.usage import StepUsage
from app.domain.models.writes import (
    ChildTalkConsent,
    LearnerUpsert,
    MarkPurgeAfterDelivery,
    ProfileChange,
    TurnWrite,
)
from app.domain.rules.conversation_machine import ConversationMachine
from app.domain.rules.onboarding_answer_parser import Found, OnboardingAnswerParser
from app.domain.rules.register_detector import RegisterDetector
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

    async def handle(
        self, ctx: TurnContext, user_text: str, interactive_ids: Sequence[str], now: datetime
    ) -> OnboardingResult:
        """Raises InvalidTransition or InvalidProfileValue only on a bug: the interpreter
        produces events the current state allows. A failed extraction call isn't raised: the
        answer counts as not understood, and the result says DEGRADED with the error's type."""
        reading = await self._read(ctx, user_text, interactive_ids, now)
        transition = ConversationMachine.transition(
            ctx.profile, len(ctx.learners), reading.event, now
        )
        return self._result(ctx, reading, transition)

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
        language = _P.language_named(user_text)
        if language is not None and not self._asks_subject(ctx):
            # "Hindi" answering "which subject do you teach?" is a subject, not a switch.
            return LanguageSwitched(language)
        if profile.state is _S.ACTIVE:
            return self._active_event(profile, user_text)
        return self._answer_event(ctx, user_text, now)

    def _first_contact(self, user_text: str, channel: Channel) -> FirstContact:
        """A greeting says nothing about the language unless it's in Devanagari ("Namaste" is
        typed by Hinglish and English speakers alike): the default then applies. On WhatsApp
        that is Hinglish (the families Marg serves); on the web demo, WEB_DEFAULT_LANGUAGE
        (English, for judges and visitors; owner, 2026-10-29)."""
        requested = _P.language_requested(user_text)
        if requested is not None:
            return FirstContact(requested, None)
        detected = RegisterDetector.detect(user_text)
        if _P.is_greeting(user_text):
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
    def _active_event(profile: UserProfile, user_text: str) -> ConversationEvent | None:
        if profile.role is Role.TEACHER:
            return TeacherAsked()
        if profile.role is Role.PARENT and _P.asks_to_add_child(user_text):
            return AddChild()
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
            return self._child_event(user_text, now.year)
        if state is _S.AWAITING_PROFILE:
            return self._profile_event(ctx, user_text)
        return None

    @staticmethod
    def _child_event(user_text: str, current_year: int) -> ConversationEvent | None:
        age = _P.parse_child_age(user_text, current_year)
        if age.problem is Found.OUT_OF_RANGE:
            return ChildInvalid(CopyKey.CHILD_INVALID_AGE)
        if age.birth_year is None:
            return None
        nickname = _P.parse_nickname(user_text)
        if nickname.problem in {Found.TOO_LONG, Found.LOOKS_LIKE_FULL_NAME}:
            return ChildInvalid(CopyKey.CHILD_NICKNAME_TOO_LONG)
        return ChildAnswered(age.birth_year, nickname.nickname)

    def _profile_event(self, ctx: TurnContext, user_text: str) -> ConversationEvent | None:
        asked = ConversationMachine.next_profile_question(ctx.profile, len(ctx.learners))
        if asked in {CopyKey.ASK_GRADE_STUDENT, CopyKey.ASK_GRADE_TEACHER}:
            return self._grade_event(user_text)
        is_short_value = (
            0 < len(user_text.split()) <= self.SHORT_VALUE_WORDS
            and "?" not in user_text
            and _P.yes_or_no(user_text) is None  # "pata nahi" is not a district
        )
        try:
            if asked is CopyKey.ASK_SUBJECT_TEACHER and is_short_value:
                return ProfileAnswered(ProfileUpdate(subject=user_text))
            if asked is CopyKey.ASK_DISTRICT and is_short_value:
                return ProfileAnswered(ProfileUpdate(district=user_text))
        except InvalidProfileValue:
            return Unrecognised()  # malformed ("12345" as a district): ask again, store nothing
        return None

    def _grade_event(self, user_text: str) -> ConversationEvent | None:
        """The class, from a short answer. A longer message may also carry a question or a
        teacher's chapter ("kal class 8 mein bal aur dabav padhana hai"): the model reads both,
        so the request isn't lost (owner, 2026-10-31)."""
        if len(user_text.split()) > self.LONG_ANSWER_WORDS:
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
        copy_keys: list[CopyKey] = []
        child_named: str | None = None
        fixed_kind = FixedReplyKind.ONBOARDING
        for effect in transition.effects:
            match effect:
                case SendCopy(key=key):
                    copy_keys.append(key)
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
        if CopyKey.DATA_DELETED in copy_keys:
            fixed_kind = FixedReplyKind.DATA_DELETED
        if CopyKey.CONSENT_DECLINED in copy_keys:
            fixed_kind = FixedReplyKind.CONSENT_DECLINED
        language = transition.profile.language or Language.HINGLISH
        shown_keys = [CHANNEL_VARIANTS.get((key, ctx.profile.channel), key) for key in copy_keys]
        if isinstance(handoff, FirstKhojHandoff) and CopyKey.ASK_CHILD_TALK in shown_keys:
            shown_keys.remove(CopyKey.ASK_CHILD_TALK)
            child_talk_question = self._reply(
                [CopyKey.ASK_CHILD_TALK], language, child_named, new_learner, fixed_kind
            )
            handoff = FirstKhojHandoff(handoff.learner, then_ask=child_talk_question)
        reply = self._reply(shown_keys, language, child_named, new_learner, fixed_kind)
        return OnboardingResult(
            reply=reply,
            writes=writes,
            handoff=handoff,
            usages=list(reading.usages),
            prompt_versions=dict(reading.prompt_versions),
            outcome=StepOutcome.DEGRADED if reading.degraded_reason else StepOutcome.OK,
            degraded_reason=reading.degraded_reason,
        )

    def _reply(
        self,
        copy_keys: Sequence[CopyKey],
        language: Language,
        child_named: str | None,
        new_learner: Learner | None,
        fixed_kind: FixedReplyKind,
    ) -> CanonicalReply:
        values = {
            "child": child_named or CHILD_FALLBACK[language],
            "invite_link": self._invite_link,
        }
        bodies: list[str] = []
        buttons: tuple[ReplyButton, ...] = ()
        for key in copy_keys:
            entry = COPY[(key, language)]
            bodies.append(entry.body.format_map(values))
            if entry.buttons:
                buttons = entry.buttons
                if key is CopyKey.ASK_CHILD_TALK and new_learner is not None:
                    buttons = tuple(
                        ReplyButton(id=f"{button.id}:{new_learner.id}", title=button.title)
                        for button in entry.buttons
                    )
        return CanonicalReply(
            body="\n\n".join(bodies),
            body_language=language,
            spoken_text=None,
            citations=[],
            buttons=list(buttons),
            fixed_kind=fixed_kind,
        )


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
            update = _ExtractionMapper._profile_update(extraction)
            if update is not None and not update.is_empty:
                question = extraction.question[:QUESTION_MAX_CHARS] if extraction.question else None
                return ProfileAnswered(update, question=question)
        if state is _S.AWAITING_CHILD and extraction.child_age is not None:
            return _ExtractionMapper._child(extraction, current_year)
        if extraction.question:
            return QuestionNoted(extraction.question[:QUESTION_MAX_CHARS])
        return None

    @staticmethod
    def _profile_update(extraction: ProfileExtraction) -> ProfileUpdate | None:
        """Out-of-range or malformed values count as absent, never as the nearest valid one."""
        grade = extraction.grade if extraction.grade in OnboardingAnswerParser.GRADES else None
        try:
            return ProfileUpdate(
                grade=grade, subject=extraction.subject, district=extraction.district
            )
        except InvalidProfileValue:
            return None

    @staticmethod
    def _child(extraction: ProfileExtraction, current_year: int) -> ConversationEvent:
        age = extraction.child_age
        if age is None or age not in OnboardingAnswerParser.CHILD_AGES:
            return ChildInvalid(CopyKey.CHILD_INVALID_AGE)
        nickname = extraction.child_nickname
        if nickname is not None:
            parsed = OnboardingAnswerParser.parse_nickname(nickname)
            if parsed.nickname is None:
                return ChildInvalid(CopyKey.CHILD_NICKNAME_TOO_LONG)
            nickname = parsed.nickname
        return ChildAnswered(current_year - age, nickname)


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
