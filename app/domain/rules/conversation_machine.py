"""ConversationMachine: the onboarding state machine (s08 §4.1 to §4.3). Pure and deterministic.

`transition` looks up (state, event type) in one table. A pair that isn't there raises
InvalidTransition naming both; it never silently does nothing. Consent comes before any profile
question on every path, a parent can't become active without a learner, and a cancelled
deletion resumes from what the profile actually holds (`resume_state`), so it can't skip consent.

MVP scope (mvp-scope §4.4, owner 2026-10-27): the student path stays designed and reachable here
(the properties cover it), but the onboarding layer answers student words with STUDENT_COMING_SOON;
a teacher's completion and later messages get the invite copy instead of a pending-question
handoff, since no teacher layer exists yet.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import ClassVar, Final

from app.core.errors import InvalidProfileValue, InvalidTransition
from app.domain.enums import (
    AgeBand,
    ConsentEventKind,
    ConversationState,
    CopyKey,
    Language,
    LearnerRelation,
    Role,
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
    Effect,
    FirstContact,
    GuardianConfirmed,
    GuardianDeclined,
    HandoffFirstKhoj,
    HandoffPendingQuestion,
    LanguageSwitched,
    ProfileAnswered,
    PurgeAfterDelivery,
    QuestionNoted,
    RecordConsent,
    RoleChosen,
    RoleUnavailable,
    SendCopy,
    SetChildTalk,
    TeacherAsked,
    Transition,
    Unrecognised,
    UpsertLearner,
)
from app.domain.models.turn import UserProfile
from app.domain.rules.stage_rules import StageRules

MAX_LEARNERS: Final = 3
CHILD_AGES: Final = range(2, 20)  # contracts §2.2: learners are 2-19 years old
STUDENT_AGE_OFFSET: Final = 6  # a student's estimated birth year: year - grade - 6 (never shown)
DEFAULT_LANGUAGE: Final = Language.HINGLISH

_S = ConversationState
_ONBOARDING_QUESTION_STATES: Final = frozenset(
    {_S.AWAITING_ROLE, _S.AWAITING_GUARDIAN, _S.AWAITING_PROFILE, _S.AWAITING_CHILD}
)


@dataclass(frozen=True, slots=True)
class _Step:
    profile: UserProfile
    learner_count: int
    now: datetime

    def moved(self, state: ConversationState, *effects: Effect, **fields: object) -> Transition:
        profile = self.profile.model_copy(update={"state": state, **fields})
        return Transition(profile=profile, effects=effects)


type _Handler = Callable[[_Step, ConversationEvent], Transition]


def _for[EventT](
    event_type: type[EventT], handle: Callable[[_Step, EventT], Transition]
) -> _Handler:
    """A table entry: `handle` only ever receives the event type it was registered for."""

    def checked(step: _Step, event: ConversationEvent) -> Transition:
        if not isinstance(event, event_type):
            raise TypeError(f"{type(event).__name__} reached the {event_type.__name__} handler")
        return handle(step, event)

    return checked


class ConversationMachine:
    @staticmethod
    def transition(
        profile: UserProfile, learner_count: int, event: ConversationEvent, now: datetime
    ) -> Transition:
        handler = _TRANSITIONS.get((profile.state, type(event)))
        if handler is None or type(event) not in ConversationMachine.allowed_events(
            profile.state, profile.role
        ):
            raise InvalidTransition(
                f"{type(event).__name__} is not allowed in {profile.state.value}"
            )
        return handler(_Step(profile, learner_count, now), event)

    @staticmethod
    def allowed_events(
        state: ConversationState, role: Role | None
    ) -> frozenset[type[ConversationEvent]]:
        allowed = {event_type for (from_state, event_type) in _TRANSITIONS if from_state == state}
        if state is _S.ACTIVE:
            if role is not Role.PARENT:
                allowed -= ConversationMachine._PARENT_ONLY
            if role is not Role.TEACHER:
                allowed.discard(TeacherAsked)
        return frozenset(allowed)

    _PARENT_ONLY: ClassVar[frozenset[type[ConversationEvent]]] = frozenset(
        {AddChild, ChildTalkAnswered}
    )

    @staticmethod
    def resume_state(profile: UserProfile, learner_count: int) -> ConversationState:
        """Where a user is, derived from what the profile holds (no "previous state" column)."""
        if profile.consented_at is None:
            return _S.AWAITING_CONSENT
        if profile.role is None:
            return _S.AWAITING_ROLE
        if profile.role is Role.STUDENT and not profile.guardian_confirmed:
            return _S.AWAITING_GUARDIAN
        if profile.role is Role.PARENT and learner_count == 0:
            return _S.AWAITING_CHILD
        if ConversationMachine.next_profile_question(profile, learner_count) is not None:
            return _S.AWAITING_PROFILE
        return _S.ACTIVE

    _PROFILE_QUESTIONS: ClassVar[Mapping[Role, tuple[tuple[str, CopyKey], ...]]] = MappingProxyType(
        {
            Role.STUDENT: (
                ("grade", CopyKey.ASK_GRADE_STUDENT),
                ("district", CopyKey.ASK_DISTRICT),
            ),
            Role.TEACHER: (
                ("subject", CopyKey.ASK_SUBJECT_TEACHER),
                ("grade", CopyKey.ASK_GRADE_TEACHER),
                ("district", CopyKey.ASK_DISTRICT),
            ),
        }
    )
    """Each role's profile fields, in the order they're asked."""

    _WAITING_FOR: ClassVar[Mapping[ConversationState, CopyKey]] = MappingProxyType(
        {
            _S.AWAITING_CONSENT: CopyKey.INTRO_CONSENT,
            _S.AWAITING_ROLE: CopyKey.ASK_ROLE,
            _S.AWAITING_GUARDIAN: CopyKey.ASK_GUARDIAN,
            _S.AWAITING_CHILD: CopyKey.ASK_CHILD,
            _S.AWAITING_DELETION_CONFIRM: CopyKey.CONFIRM_DELETE,
        }
    )

    @staticmethod
    def next_profile_question(profile: UserProfile, learner_count: int) -> CopyKey | None:
        """The next thing to ask; None when the role's profile is complete."""
        if profile.role is Role.PARENT:
            return CopyKey.ASK_CHILD if learner_count == 0 else None
        if profile.role is None:
            return None
        for field_name, question in ConversationMachine._PROFILE_QUESTIONS[profile.role]:
            if getattr(profile, field_name) is None:
                return question
        return None

    @staticmethod
    def question_for(profile: UserProfile, learner_count: int) -> CopyKey | None:
        """The question a state is waiting on, to ask again after an interruption."""
        if profile.state is _S.AWAITING_PROFILE:
            return ConversationMachine.next_profile_question(profile, learner_count)
        return ConversationMachine._WAITING_FOR.get(profile.state)


# --- handlers ----------------------------------------------------------------------------------


def _first_contact(step: _Step, event: FirstContact) -> Transition:
    intro = CopyKey.INTRO_CONSENT_WITH_QUESTION if event.pending_question else CopyKey.INTRO_CONSENT
    return step.moved(
        _S.AWAITING_CONSENT,
        SendCopy(intro),
        language=event.detected_language or DEFAULT_LANGUAGE,
        pending_question=event.pending_question,
    )


def _consent_given(step: _Step, event: ConsentGiven) -> Transition:
    return step.moved(
        _S.AWAITING_ROLE,
        RecordConsent(ConsentEventKind.GRANTED),
        SendCopy(CopyKey.ASK_ROLE),
        consented_at=step.now,
    )


def _consent_declined(step: _Step, event: ConsentDeclined) -> Transition:
    return step.moved(_S.AWAITING_CONSENT, SendCopy(CopyKey.CONSENT_DECLINED), PurgeAfterDelivery())


def _role_chosen(step: _Step, event: RoleChosen) -> Transition:
    if event.role is Role.STUDENT:
        return step.moved(_S.AWAITING_GUARDIAN, SendCopy(CopyKey.ASK_GUARDIAN), role=event.role)
    if event.role is Role.PARENT:
        return step.moved(_S.AWAITING_CHILD, SendCopy(CopyKey.ASK_CHILD), role=event.role)
    teacher = step.profile.model_copy(update={"role": event.role})
    question = ConversationMachine.next_profile_question(teacher, step.learner_count)
    if question is None:
        raise InvalidTransition("a teacher's profile can't be complete before any answer")
    return step.moved(_S.AWAITING_PROFILE, SendCopy(question), role=event.role)


def _role_unavailable(step: _Step, event: RoleUnavailable) -> Transition:
    return step.moved(
        _S.AWAITING_ROLE, SendCopy(CopyKey.STUDENT_COMING_SOON), SendCopy(CopyKey.ASK_ROLE)
    )


def _guardian_confirmed(step: _Step, event: GuardianConfirmed) -> Transition:
    student = step.profile.model_copy(update={"guardian_confirmed": True})
    question = ConversationMachine.next_profile_question(student, step.learner_count)
    if question is None:
        raise InvalidTransition("a student's profile can't be complete before any answer")
    return step.moved(
        _S.AWAITING_PROFILE,
        RecordConsent(ConsentEventKind.GUARDIAN_CONFIRMED),
        SendCopy(question),
        guardian_confirmed=True,
    )


def _guardian_declined(step: _Step, event: GuardianDeclined) -> Transition:
    return step.moved(_S.AWAITING_GUARDIAN, SendCopy(CopyKey.GUARDIAN_NEEDED))


def _profile_answered(step: _Step, event: ProfileAnswered) -> Transition:
    update = event.update
    fields: dict[str, object] = {}
    pending = event.question or step.profile.pending_question
    if update.grade is not None:
        fields["grade"] = update.grade
    if update.subject is not None:
        fields["subject"] = update.subject.strip()
    if update.district is not None:
        fields["district"] = update.district.strip()
    answered = step.profile.model_copy(update=fields)
    question = ConversationMachine.next_profile_question(answered, step.learner_count)
    if question is not None:
        return step.moved(
            _S.AWAITING_PROFILE, SendCopy(question), pending_question=pending, **fields
        )
    if answered.role is Role.TEACHER:
        # A chapter sent during onboarding is answered now, after the invite (owner, 2026-10-31)
        teacher_effects: list[Effect] = [SendCopy(CopyKey.PROFILE_DONE_TEACHER)]
        if pending:
            teacher_effects.append(HandoffPendingQuestion(pending))
        return step.moved(_S.ACTIVE, *teacher_effects, pending_question=None, **fields)
    effects: list[Effect] = [SendCopy(CopyKey.PROFILE_DONE)]
    if answered.grade is not None:
        birth_year = step.now.year - answered.grade - STUDENT_AGE_OFFSET
        effects.insert(0, UpsertLearner(LearnerRelation.SELF, birth_year, nickname=None))
    if pending:
        effects.append(HandoffPendingQuestion(pending))
    return step.moved(_S.ACTIVE, *effects, pending_question=None, **fields)


def _child_answered(step: _Step, event: ChildAnswered) -> Transition:
    age = step.now.year - event.birth_year
    if age not in CHILD_AGES:
        raise InvalidProfileValue(f"birth_year {event.birth_year} gives age {age}, outside 2-19")
    if step.learner_count >= MAX_LEARNERS:
        return step.moved(_S.ACTIVE, SendCopy(CopyKey.MAX_CHILDREN))
    nickname = event.nickname.strip() if event.nickname else None
    effects: list[Effect] = [UpsertLearner(LearnerRelation.PARENT, event.birth_year, nickname)]
    if StageRules.age_band(event.birth_year, step.now.date()) is not AgeBand.FOUNDATIONAL_3_8:
        # The daily khoj and child talk are for 3-8-year-olds: no khoj promised or sent, no
        # child talk offered and no daily time asked; the parent can still ask anything.
        if step.learner_count == 0:
            effects.append(RecordConsent(ConsentEventKind.CHILD_PROFILE_CONSENT))
        effects.append(SendCopy(CopyKey.PROFILE_DONE_PARENT_OTHER_AGE))
        return step.moved(_S.ACTIVE, *effects, pending_question=None)
    if step.learner_count == 0:
        # The first child completes onboarding: consent for the child's profile, then the first
        # khoj in the same turn, with the child-talk question (C13) in the preamble.
        effects += [
            RecordConsent(ConsentEventKind.CHILD_PROFILE_CONSENT),
            SendCopy(CopyKey.PROFILE_DONE_PARENT),
            SendCopy(CopyKey.ASK_CHILD_TALK),
            HandoffFirstKhoj(),
        ]
    else:
        effects += [SendCopy(CopyKey.PROFILE_DONE_PARENT), HandoffFirstKhoj()]
    # A parent's pending question is dropped: the first khoj is the answer (s08 Q5).
    return step.moved(_S.ACTIVE, *effects, pending_question=None)


def _child_invalid(step: _Step, event: ChildInvalid) -> Transition:
    return step.moved(_S.AWAITING_CHILD, SendCopy(event.reason))


def _add_child(step: _Step, event: AddChild) -> Transition:
    if step.learner_count >= MAX_LEARNERS:
        return step.moved(_S.ACTIVE, SendCopy(CopyKey.MAX_CHILDREN))
    return step.moved(_S.AWAITING_CHILD, SendCopy(CopyKey.ASK_CHILD))


def _child_talk_answered(step: _Step, event: ChildTalkAnswered) -> Transition:
    if event.allowed:
        return step.moved(
            _S.ACTIVE,
            SetChildTalk(event.learner_id, granted=True),
            RecordConsent(ConsentEventKind.CHILD_TALK_CONSENT),
            SendCopy(CopyKey.CHILD_TALK_ENABLED),
        )
    return step.moved(
        _S.ACTIVE, SetChildTalk(event.learner_id, granted=False), SendCopy(CopyKey.CHILD_TALK_OFF)
    )


def _teacher_asked(step: _Step, event: TeacherAsked) -> Transition:
    return step.moved(_S.ACTIVE, SendCopy(CopyKey.TEACHER_WAITING))


def _language_switched(step: _Step, event: LanguageSwitched) -> Transition:
    state = step.profile.state
    switched = step.profile.model_copy(update={"language": event.language})
    if state is _S.ACTIVE:
        effects: tuple[Effect, ...] = (SendCopy(CopyKey.LANGUAGE_CHANGED),)
    else:
        question = ConversationMachine.question_for(switched, step.learner_count)
        effects = (SendCopy(question),) if question else ()
    return step.moved(state, *effects, language=event.language)


def _question_noted(step: _Step, event: QuestionNoted) -> Transition:
    state = step.profile.state
    if state is _S.AWAITING_CONSENT:
        return step.moved(
            state, SendCopy(CopyKey.INTRO_CONSENT_WITH_QUESTION), pending_question=event.question
        )
    question = ConversationMachine.question_for(step.profile, step.learner_count)
    effects: list[Effect] = [SendCopy(CopyKey.QUESTION_NOTED)]
    if question:
        effects.append(SendCopy(question))
    return step.moved(state, *effects, pending_question=event.question)


def _unrecognised(step: _Step, event: Unrecognised) -> Transition:
    state = step.profile.state
    if state is _S.AWAITING_DELETION_CONFIRM:
        return step.moved(state, SendCopy(CopyKey.CONFIRM_DELETE))
    question = ConversationMachine.question_for(step.profile, step.learner_count)
    effects: list[Effect] = [] if event.greeted and question else [SendCopy(event.not_understood)]
    if question:
        effects.append(SendCopy(question))
    return step.moved(state, *effects)


def _deletion_requested(step: _Step, event: DeletionRequested) -> Transition:
    return step.moved(_S.AWAITING_DELETION_CONFIRM, SendCopy(CopyKey.CONFIRM_DELETE))


def _deletion_confirmed(step: _Step, event: DeletionConfirmed) -> Transition:
    return step.moved(
        _S.AWAITING_DELETION_CONFIRM,
        RecordConsent(ConsentEventKind.DELETION_REQUESTED),
        SendCopy(CopyKey.DATA_DELETED),
        PurgeAfterDelivery(),
    )


def _deletion_cancelled(step: _Step, event: DeletionCancelled) -> Transition:
    resumed = ConversationMachine.resume_state(step.profile, step.learner_count)
    resumed_profile = step.profile.model_copy(update={"state": resumed})
    question = ConversationMachine.question_for(resumed_profile, step.learner_count)
    effects: list[Effect] = [SendCopy(CopyKey.DELETE_CANCELLED)]
    if question:
        effects.append(SendCopy(question))
    return step.moved(resumed, *effects)


def _table() -> Mapping[tuple[ConversationState, type[ConversationEvent]], _Handler]:
    table: dict[tuple[ConversationState, type[ConversationEvent]], _Handler] = {
        (_S.NEW, FirstContact): _for(FirstContact, _first_contact),
        (_S.AWAITING_CONSENT, ConsentGiven): _for(ConsentGiven, _consent_given),
        (_S.AWAITING_CONSENT, ConsentDeclined): _for(ConsentDeclined, _consent_declined),
        (_S.AWAITING_ROLE, RoleChosen): _for(RoleChosen, _role_chosen),
        (_S.AWAITING_ROLE, RoleUnavailable): _for(RoleUnavailable, _role_unavailable),
        (_S.AWAITING_GUARDIAN, GuardianConfirmed): _for(GuardianConfirmed, _guardian_confirmed),
        (_S.AWAITING_GUARDIAN, GuardianDeclined): _for(GuardianDeclined, _guardian_declined),
        (_S.AWAITING_PROFILE, ProfileAnswered): _for(ProfileAnswered, _profile_answered),
        (_S.AWAITING_CHILD, ChildAnswered): _for(ChildAnswered, _child_answered),
        (_S.AWAITING_CHILD, ChildInvalid): _for(ChildInvalid, _child_invalid),
        (_S.ACTIVE, AddChild): _for(AddChild, _add_child),
        (_S.ACTIVE, ChildTalkAnswered): _for(ChildTalkAnswered, _child_talk_answered),
        (_S.ACTIVE, TeacherAsked): _for(TeacherAsked, _teacher_asked),
        (_S.ACTIVE, LanguageSwitched): _for(LanguageSwitched, _language_switched),
        (_S.ACTIVE, Unrecognised): _for(Unrecognised, _unrecognised),
        (_S.AWAITING_CONSENT, LanguageSwitched): _for(LanguageSwitched, _language_switched),
        (_S.AWAITING_CONSENT, QuestionNoted): _for(QuestionNoted, _question_noted),
        (_S.AWAITING_CONSENT, Unrecognised): _for(Unrecognised, _unrecognised),
        (_S.AWAITING_DELETION_CONFIRM, DeletionConfirmed): _for(
            DeletionConfirmed, _deletion_confirmed
        ),
        (_S.AWAITING_DELETION_CONFIRM, DeletionCancelled): _for(
            DeletionCancelled, _deletion_cancelled
        ),
        (_S.AWAITING_DELETION_CONFIRM, Unrecognised): _for(Unrecognised, _unrecognised),
    }
    for state in _ONBOARDING_QUESTION_STATES:
        table[(state, LanguageSwitched)] = _for(LanguageSwitched, _language_switched)
        table[(state, QuestionNoted)] = _for(QuestionNoted, _question_noted)
        table[(state, Unrecognised)] = _for(Unrecognised, _unrecognised)
    for state in ConversationState:
        if state is not _S.AWAITING_DELETION_CONFIRM:
            table[(state, DeletionRequested)] = _for(DeletionRequested, _deletion_requested)
    return MappingProxyType(table)


_TRANSITIONS: Final = _table()
