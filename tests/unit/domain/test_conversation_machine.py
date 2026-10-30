"""ConversationMachine: the onboarding state machine (s08 §4.3, §9; CLAUDE.md §3).

Properties run over generated event sequences from NEW, with the learner count tracked from the
machine's own UpsertLearner effects. Disallowed events must raise InvalidTransition and leave the
simulation where it was; allowed ones are applied.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.errors import InvalidProfileValue, InvalidTransition
from app.domain.enums import (
    Channel,
    ConsentEventKind,
    ConversationState,
    CopyKey,
    Language,
    LearnerRelation,
    Role,
)
from app.domain.models.base import UserHash
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
    RoleUnavailable,
    SendCopy,
    SetChildTalk,
    TeacherAsked,
    Transition,
    Unrecognised,
    UpsertLearner,
)
from app.domain.models.learner import LearnerId
from app.domain.models.turn import UserProfile
from app.domain.rules.conversation_machine import MAX_LEARNERS, ConversationMachine

pytestmark = pytest.mark.unit

S = ConversationState
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
LEARNER = LearnerId(UUID(int=7))
QUESTION = "Mujhe pilot banna hai"


def new_profile() -> UserProfile:
    return UserProfile(
        user_hash=UserHash("d" * 64),
        channel=Channel.WHATSAPP,
        state=S.NEW,
        role=None,
        grade=None,
        subject=None,
        district=None,
        language=None,
        guardian_confirmed=False,
        consented_at=None,
        last_inbound_at=None,
        pending_question=None,
    )


def at(state: ConversationState, **fields: object) -> UserProfile:
    return new_profile().model_copy(update={"state": state, **fields})


CONSENTED = {"consented_at": NOW, "language": Language.HINGLISH}


def step(profile: UserProfile, event: ConversationEvent, learners: int = 0) -> Transition:
    return ConversationMachine.transition(profile, learners, event, NOW)


def copies(transition: Transition) -> list[CopyKey]:
    return [effect.key for effect in transition.effects if isinstance(effect, SendCopy)]


# --- the happy paths ---------------------------------------------------------------------------


def test_first_contact_with_a_question_remembers_it_and_says_so() -> None:
    moved = step(new_profile(), FirstContact(Language.HINDI, QUESTION))
    assert moved.profile.state is S.AWAITING_CONSENT
    assert moved.profile.pending_question == QUESTION
    assert moved.profile.language is Language.HINDI
    assert copies(moved) == [CopyKey.INTRO_CONSENT_WITH_QUESTION]


def test_first_contact_without_a_language_defaults_to_hinglish() -> None:
    moved = step(new_profile(), FirstContact(None, None))
    assert moved.profile.language is Language.HINGLISH
    assert copies(moved) == [CopyKey.INTRO_CONSENT]


def test_consent_records_the_event_and_asks_the_role() -> None:
    moved = step(at(S.AWAITING_CONSENT), ConsentGiven())
    assert moved.profile.state is S.AWAITING_ROLE
    assert moved.profile.consented_at == NOW
    assert RecordConsent(ConsentEventKind.GRANTED) in moved.effects
    assert copies(moved) == [CopyKey.ASK_ROLE]


def test_declining_consent_purges_after_the_reply() -> None:
    moved = step(at(S.AWAITING_CONSENT), ConsentDeclined())
    assert PurgeAfterDelivery() in moved.effects
    assert copies(moved) == [CopyKey.CONSENT_DECLINED]


def test_a_parent_answers_one_question_about_the_child_and_gets_the_first_khoj() -> None:
    parent = step(at(S.AWAITING_ROLE, **CONSENTED), RoleChosen(Role.PARENT))
    assert parent.profile.state is S.AWAITING_CHILD
    done = step(parent.profile, ChildAnswered(2021, "Munni"))
    assert done.profile.state is S.ACTIVE
    assert done.effects == (
        UpsertLearner(LearnerRelation.PARENT, 2021, "Munni"),
        RecordConsent(ConsentEventKind.CHILD_PROFILE_CONSENT),
        SendCopy(CopyKey.PROFILE_DONE_PARENT),
        SendCopy(CopyKey.ASK_CHILD_TALK),
        HandoffFirstKhoj(),
    )


def test_a_parents_pending_question_is_dropped_for_the_first_khoj() -> None:
    profile = at(S.AWAITING_CHILD, role=Role.PARENT, pending_question=QUESTION, **CONSENTED)
    done = step(profile, ChildAnswered(2020, None))
    assert done.profile.pending_question is None
    assert not any(isinstance(effect, HandoffPendingQuestion) for effect in done.effects)


def test_a_second_child_gets_its_own_khoj_without_asking_consent_again() -> None:
    profile = at(S.AWAITING_CHILD, role=Role.PARENT, **CONSENTED)
    done = step(profile, ChildAnswered(2022, None), learners=1)
    assert RecordConsent(ConsentEventKind.CHILD_PROFILE_CONSENT) not in done.effects
    assert CopyKey.ASK_CHILD_TALK not in copies(done)
    assert HandoffFirstKhoj() in done.effects


@pytest.mark.parametrize(("birth_year", "age"), [(2016, 10), (2017, 9), (2024, 2), (2010, 16)])
def test_a_child_outside_3_to_8_gets_no_khoj_child_talk_or_daily_time(
    birth_year: int, age: int
) -> None:
    # regression (a mother's voice note, 2026-10-29): a 10-year-old was promised a khoj, then
    # told it was for 3-8 only, and offered child talk and daily times
    profile = at(S.AWAITING_CHILD, role=Role.PARENT, **CONSENTED)
    done = step(profile, ChildAnswered(birth_year, "Lala"))
    assert NOW.year - birth_year == age
    assert done.profile.state is S.ACTIVE
    assert done.effects == (
        UpsertLearner(LearnerRelation.PARENT, birth_year, "Lala"),
        RecordConsent(ConsentEventKind.CHILD_PROFILE_CONSENT),
        SendCopy(CopyKey.PROFILE_DONE_PARENT_OTHER_AGE),
    )


@pytest.mark.parametrize("birth_year", [2018, 2023])  # exactly 8 and exactly 3 still get it
def test_the_khoj_age_boundaries_are_exact(birth_year: int) -> None:
    profile = at(S.AWAITING_CHILD, role=Role.PARENT, **CONSENTED)
    done = step(profile, ChildAnswered(birth_year, None))
    assert HandoffFirstKhoj() in done.effects
    assert CopyKey.PROFILE_DONE_PARENT_OTHER_AGE not in copies(done)


def test_a_second_child_outside_3_to_8_gets_the_same_without_consent_again() -> None:
    profile = at(S.AWAITING_CHILD, role=Role.PARENT, **CONSENTED)
    done = step(profile, ChildAnswered(2016, None), learners=1)
    assert done.effects == (
        UpsertLearner(LearnerRelation.PARENT, 2016, None),
        SendCopy(CopyKey.PROFILE_DONE_PARENT_OTHER_AGE),
    )


def test_a_teacher_answers_subject_grade_district_and_gets_the_invite() -> None:
    teacher = step(at(S.AWAITING_ROLE, **CONSENTED), RoleChosen(Role.TEACHER))
    assert copies(teacher) == [CopyKey.ASK_SUBJECT_TEACHER]
    subject = step(teacher.profile, ProfileAnswered(ProfileUpdate(subject="Hindi")))
    assert copies(subject) == [CopyKey.ASK_GRADE_TEACHER]
    grade = step(subject.profile, ProfileAnswered(ProfileUpdate(grade=3)))
    assert copies(grade) == [CopyKey.ASK_DISTRICT]
    done = step(grade.profile, ProfileAnswered(ProfileUpdate(district="Barmer")))
    assert done.profile.state is S.ACTIVE
    assert copies(done) == [CopyKey.PROFILE_DONE_TEACHER]
    assert not any(isinstance(effect, UpsertLearner) for effect in done.effects)


CHAPTER = "Kal class 8 mein bal aur dabav padhana hai"


def test_a_teachers_chapter_sent_with_the_class_is_answered_when_onboarding_ends() -> None:
    """Owner, 2026-10-31: the chapter was lost when it arrived as the class answer."""
    teacher = at(S.AWAITING_PROFILE, role=Role.TEACHER, subject="Science", **CONSENTED)
    graded = step(teacher, ProfileAnswered(ProfileUpdate(grade=8), question=CHAPTER))
    assert graded.profile.state is S.AWAITING_PROFILE
    assert graded.profile.pending_question == CHAPTER
    assert copies(graded) == [CopyKey.ASK_DISTRICT]
    done = step(graded.profile, ProfileAnswered(ProfileUpdate(district="Karauli")))
    assert done.profile.state is S.ACTIVE
    assert copies(done) == [CopyKey.PROFILE_DONE_TEACHER]
    assert HandoffPendingQuestion(CHAPTER) in done.effects
    assert done.profile.pending_question is None


def test_a_teacher_with_nothing_pending_gets_only_the_invite() -> None:
    teacher = at(S.AWAITING_PROFILE, role=Role.TEACHER, subject="Science", grade=8, **CONSENTED)
    done = step(teacher, ProfileAnswered(ProfileUpdate(district="Karauli")))
    assert not any(isinstance(effect, HandoffPendingQuestion) for effect in done.effects)


def test_a_question_with_the_last_answer_is_handed_off_at_once() -> None:
    student = at(
        S.AWAITING_PROFILE, role=Role.STUDENT, guardian_confirmed=True, grade=10, **CONSENTED
    )
    done = step(student, ProfileAnswered(ProfileUpdate(district="Karauli"), question=QUESTION))
    assert HandoffPendingQuestion(QUESTION) in done.effects


def test_a_newer_question_replaces_the_older_one() -> None:
    teacher = at(
        S.AWAITING_PROFILE,
        role=Role.TEACHER,
        subject="Science",
        pending_question="purana sawaal",
        **CONSENTED,
    )
    graded = step(teacher, ProfileAnswered(ProfileUpdate(grade=8), question=CHAPTER))
    assert graded.profile.pending_question == CHAPTER


def test_an_answer_without_a_question_keeps_the_one_waiting() -> None:
    teacher = at(
        S.AWAITING_PROFILE,
        role=Role.TEACHER,
        subject="Science",
        pending_question=CHAPTER,
        **CONSENTED,
    )
    graded = step(teacher, ProfileAnswered(ProfileUpdate(grade=8)))
    assert graded.profile.pending_question == CHAPTER


def test_several_profile_fields_in_one_answer_skip_their_questions() -> None:
    teacher = at(S.AWAITING_PROFILE, role=Role.TEACHER, subject="Maths", **CONSENTED)
    done = step(teacher, ProfileAnswered(ProfileUpdate(grade=9, district="Barmer")))
    assert done.profile.state is S.ACTIVE


def test_an_active_teacher_gets_the_waiting_copy() -> None:
    teacher = at(S.ACTIVE, role=Role.TEACHER, subject="Maths", grade=9, district="X", **CONSENTED)
    assert copies(step(teacher, TeacherAsked())) == [CopyKey.TEACHER_WAITING]


def test_a_student_needs_the_guardian_and_gets_a_self_learner_and_the_handoff() -> None:
    student = step(at(S.AWAITING_ROLE, **CONSENTED), RoleChosen(Role.STUDENT))
    assert student.profile.state is S.AWAITING_GUARDIAN
    guardian = step(student.profile, GuardianConfirmed())
    assert RecordConsent(ConsentEventKind.GUARDIAN_CONFIRMED) in guardian.effects
    with_question = guardian.profile.model_copy(update={"pending_question": QUESTION})
    done = step(with_question, ProfileAnswered(ProfileUpdate(grade=9, district="Barmer")))
    assert done.profile.state is S.ACTIVE
    assert UpsertLearner(LearnerRelation.SELF, 2026 - 9 - 6, None) in done.effects
    assert HandoffPendingQuestion(QUESTION) in done.effects
    assert done.profile.pending_question is None


def test_student_words_get_coming_soon_and_the_role_question_again() -> None:
    moved = step(at(S.AWAITING_ROLE, **CONSENTED), RoleUnavailable(Role.STUDENT))
    assert moved.profile.state is S.AWAITING_ROLE
    assert copies(moved) == [CopyKey.STUDENT_COMING_SOON, CopyKey.ASK_ROLE]


@pytest.mark.parametrize("allowed", [True, False])
def test_child_talk_consent_is_recorded_only_when_granted(*, allowed: bool) -> None:
    parent = at(S.ACTIVE, role=Role.PARENT, **CONSENTED)
    moved = step(parent, ChildTalkAnswered(LEARNER, allowed=allowed), learners=1)
    assert SetChildTalk(LEARNER, granted=allowed) in moved.effects
    recorded = RecordConsent(ConsentEventKind.CHILD_TALK_CONSENT) in moved.effects
    assert recorded is allowed


# --- interruptions, deletion -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "question"),
    [
        (S.AWAITING_ROLE, CopyKey.ASK_ROLE),
        (S.AWAITING_CHILD, CopyKey.ASK_CHILD),
        (S.AWAITING_GUARDIAN, CopyKey.ASK_GUARDIAN),
    ],
)
def test_an_unclear_answer_is_re_asked(state: ConversationState, question: CopyKey) -> None:
    role = Role.PARENT if state is S.AWAITING_CHILD else Role.STUDENT
    profile = at(state, role=None if state is S.AWAITING_ROLE else role, **CONSENTED)
    assert copies(step(profile, Unrecognised())) == [CopyKey.NOT_UNDERSTOOD, question]


def test_a_grade_outside_1_to_12_says_so() -> None:
    teacher = at(S.AWAITING_PROFILE, role=Role.TEACHER, subject="Maths", **CONSENTED)
    moved = step(teacher, Unrecognised(not_understood=CopyKey.INVALID_GRADE))
    assert copies(moved) == [CopyKey.INVALID_GRADE, CopyKey.ASK_GRADE_TEACHER]


def test_a_question_during_onboarding_is_kept_and_the_question_re_asked() -> None:
    moved = step(at(S.AWAITING_ROLE, **CONSENTED), QuestionNoted(QUESTION))
    assert moved.profile.pending_question == QUESTION
    assert copies(moved) == [CopyKey.QUESTION_NOTED, CopyKey.ASK_ROLE]


def test_switching_language_mid_onboarding_re_asks_in_the_new_language() -> None:
    moved = step(at(S.AWAITING_ROLE, **CONSENTED), LanguageSwitched(Language.ENGLISH))
    assert moved.profile.language is Language.ENGLISH
    assert copies(moved) == [CopyKey.ASK_ROLE]


def test_deletion_confirmed_records_it_and_purges_after_the_reply() -> None:
    asked = step(at(S.ACTIVE, role=Role.PARENT, **CONSENTED), DeletionRequested(), learners=1)
    assert copies(asked) == [CopyKey.CONFIRM_DELETE]
    done = step(asked.profile, DeletionConfirmed(), learners=1)
    assert RecordConsent(ConsentEventKind.DELETION_REQUESTED) in done.effects
    assert PurgeAfterDelivery() in done.effects
    assert copies(done) == [CopyKey.DATA_DELETED]


def test_deletion_cancelled_by_a_new_user_returns_to_consent_not_active() -> None:
    asked = step(new_profile(), DeletionRequested())
    cancelled = step(asked.profile, DeletionCancelled())
    assert cancelled.profile.state is S.AWAITING_CONSENT
    assert copies(cancelled) == [CopyKey.DELETE_CANCELLED, CopyKey.INTRO_CONSENT]


def test_deletion_cancelled_by_a_parent_with_a_child_resumes_active() -> None:
    profile = at(S.AWAITING_DELETION_CONFIRM, role=Role.PARENT, **CONSENTED)
    cancelled = step(profile, DeletionCancelled(), learners=1)
    assert cancelled.profile.state is S.ACTIVE
    assert copies(cancelled) == [CopyKey.DELETE_CANCELLED]


# --- negatives ---------------------------------------------------------------------------------


def test_consent_in_active_is_an_invalid_transition_naming_both() -> None:
    with pytest.raises(InvalidTransition, match="ConsentGiven is not allowed in active"):
        step(at(S.ACTIVE, role=Role.PARENT, **CONSENTED), ConsentGiven(), learners=1)


@pytest.mark.parametrize("role", [Role.TEACHER, Role.STUDENT])
def test_add_child_is_only_for_parents(role: Role) -> None:
    assert AddChild not in ConversationMachine.allowed_events(S.ACTIVE, role)
    with pytest.raises(InvalidTransition, match="AddChild is not allowed in active"):
        step(at(S.ACTIVE, role=role, **CONSENTED), AddChild())


def test_teacher_asked_is_only_for_teachers() -> None:
    with pytest.raises(InvalidTransition, match="TeacherAsked"):
        step(at(S.ACTIVE, role=Role.PARENT, **CONSENTED), TeacherAsked(), learners=1)


@pytest.mark.parametrize("birth_year", [2025, 2006, 1990, 2030])
def test_a_child_outside_2_to_19_is_refused(birth_year: int) -> None:
    with pytest.raises(InvalidProfileValue, match="birth_year"):
        step(at(S.AWAITING_CHILD, role=Role.PARENT, **CONSENTED), ChildAnswered(birth_year, None))


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"grade": 0}, "grade 0 is outside 1-12"),
        ({"grade": 13}, "grade 13 is outside 1-12"),
        ({"district": ""}, "district"),
        ({"district": "   "}, "district"),
        ({"district": "12345"}, "district"),
        ({"district": "x" * 61}, "district"),
        ({"subject": ""}, "subject"),
        ({"subject": "x" * 41}, "subject"),
    ],
)
def test_bad_profile_values_are_refused_naming_the_field(
    fields: dict[str, object], message: str
) -> None:
    with pytest.raises(InvalidProfileValue, match=message):
        ProfileUpdate(**fields)  # type: ignore[arg-type]  # deliberately mixed value types


@pytest.mark.parametrize("nickname", ["", "   ", "x" * 21, "123"])
def test_bad_nicknames_are_refused(nickname: str) -> None:
    with pytest.raises(InvalidProfileValue, match="nickname"):
        ChildAnswered(2021, nickname)


def test_a_fourth_child_is_refused_by_the_machine() -> None:
    profile = at(S.AWAITING_CHILD, role=Role.PARENT, **CONSENTED)
    done = step(profile, ChildAnswered(2021, None), learners=MAX_LEARNERS)
    assert copies(done) == [CopyKey.MAX_CHILDREN]
    assert not any(isinstance(effect, UpsertLearner) for effect in done.effects)


# --- properties --------------------------------------------------------------------------------

NICKNAMES = st.one_of(st.none(), st.sampled_from(["Munni", "मुन्नी", "Golu", "Chhotu"]))
EVENTS: st.SearchStrategy[ConversationEvent] = st.one_of(
    st.builds(
        FirstContact,
        detected_language=st.one_of(st.none(), st.sampled_from(Language)),
        pending_question=st.one_of(st.none(), st.just(QUESTION), st.just("kya karein 😊")),
    ),
    st.just(ConsentGiven()),
    st.just(ConsentDeclined()),
    st.builds(RoleChosen, role=st.sampled_from(Role)),
    st.just(RoleUnavailable(Role.STUDENT)),
    st.just(GuardianConfirmed()),
    st.just(GuardianDeclined()),
    st.builds(
        ProfileAnswered,
        update=st.builds(
            ProfileUpdate,
            grade=st.one_of(st.none(), st.integers(1, 12)),
            subject=st.one_of(st.none(), st.sampled_from(["Maths", "हिंदी"])),
            district=st.one_of(st.none(), st.sampled_from(["Barmer", "बहराइच"])),
        ),
    ),
    st.builds(
        ChildAnswered, birth_year=st.integers(NOW.year - 19, NOW.year - 2), nickname=NICKNAMES
    ),
    st.builds(
        ChildInvalid,
        reason=st.sampled_from([CopyKey.CHILD_INVALID_AGE, CopyKey.CHILD_NICKNAME_TOO_LONG]),
    ),
    st.just(AddChild()),
    st.builds(ChildTalkAnswered, learner_id=st.just(LEARNER), allowed=st.booleans()),
    st.just(TeacherAsked()),
    st.builds(LanguageSwitched, language=st.sampled_from(Language)),
    st.builds(QuestionNoted, question=st.sampled_from([QUESTION, "बच्चा क्यों रोता है?", "🙏"])),
    st.builds(Unrecognised),
    st.just(DeletionRequested()),
    st.just(DeletionConfirmed()),
    st.just(DeletionCancelled()),
)


@dataclass
class Journey:
    """One simulated user: the profile, learners made, and what happened on the way."""

    profile: UserProfile = field(default_factory=new_profile)
    learners: int = 0
    states: list[ConversationState] = field(default_factory=lambda: [S.NEW])
    applied: list[ConversationEvent] = field(default_factory=list)
    consents: list[ConsentEventKind] = field(default_factory=list)
    upserts: int = 0

    def offer(self, event: ConversationEvent) -> None:
        allowed = ConversationMachine.allowed_events(self.profile.state, self.profile.role)
        if type(event) not in allowed:
            with pytest.raises(InvalidTransition, match=type(event).__name__):
                ConversationMachine.transition(self.profile, self.learners, event, NOW)
            return
        moved = ConversationMachine.transition(self.profile, self.learners, event, NOW)
        for effect in moved.effects:
            if isinstance(effect, UpsertLearner):
                self.learners += 1
                self.upserts += 1
            if isinstance(effect, RecordConsent):
                self.consents.append(effect.kind)
        self.profile = moved.profile
        self.applied.append(event)
        self.states.append(moved.profile.state)


def walk(events: list[ConversationEvent]) -> Journey:
    journey = Journey()
    for event in events:
        journey.offer(event)
    return journey


COMPLETION_STEP: dict[ConversationState, ConversationEvent] = {
    S.NEW: FirstContact(None, None),
    S.AWAITING_CONSENT: ConsentGiven(),
    S.AWAITING_ROLE: RoleChosen(Role.PARENT),
    S.AWAITING_GUARDIAN: GuardianConfirmed(),
    S.AWAITING_PROFILE: ProfileAnswered(ProfileUpdate(grade=5, subject="Maths", district="Barmer")),
    S.AWAITING_CHILD: ChildAnswered(NOW.year - 5, None),
    S.AWAITING_DELETION_CONFIRM: DeletionCancelled(),
}
"""One step towards ACTIVE from every other state: the path the property says always exists."""


@settings(max_examples=300)
@given(events=st.lists(EVENTS, max_size=25))
def test_every_reachable_state_has_a_path_to_active(events: list[ConversationEvent]) -> None:
    journey = walk(events)
    for _ in range(8):
        if journey.profile.state is S.ACTIVE:
            break
        journey.offer(COMPLETION_STEP[journey.profile.state])
    assert journey.profile.state is S.ACTIVE


@settings(max_examples=300)
@given(events=st.lists(EVENTS, max_size=30))
def test_consent_can_never_be_bypassed(events: list[ConversationEvent]) -> None:
    journey = walk(events)
    for index, state in enumerate(journey.states):
        if state is not S.ACTIVE:
            continue
        before = journey.applied[:index]
        assert any(isinstance(event, ConsentGiven) for event in before)
    if S.ACTIVE in journey.states:
        assert journey.profile.consented_at is not None


@settings(max_examples=300)
@given(events=st.lists(EVENTS, max_size=30))
def test_role_paths_hold(events: list[ConversationEvent]) -> None:
    journey = walk(events)
    if journey.profile.role is Role.PARENT:
        assert S.AWAITING_GUARDIAN not in journey.states[journey.states.index(S.AWAITING_ROLE) :]
        if S.ACTIVE in journey.states:
            assert journey.learners >= 1
            assert ConsentEventKind.CHILD_PROFILE_CONSENT in journey.consents
    if journey.profile.role is Role.STUDENT and S.ACTIVE in journey.states:
        assert any(isinstance(event, GuardianConfirmed) for event in journey.applied)


@settings(max_examples=300)
@given(events=st.lists(EVENTS, max_size=40))
def test_a_user_never_has_more_than_three_learners(events: list[ConversationEvent]) -> None:
    assert walk(events).upserts <= MAX_LEARNERS


@settings(max_examples=300)
@given(events=st.lists(EVENTS, max_size=30))
def test_no_transition_erases_collected_data(events: list[ConversationEvent]) -> None:
    journey = Journey()
    for event in events:
        before = journey.profile
        journey.offer(event)
        after = journey.profile
        for name in ("consented_at", "role", "grade", "subject", "district", "language"):
            if getattr(before, name) is not None:
                assert getattr(after, name) is not None, name


@given(
    state=st.sampled_from(ConversationState),
    role=st.one_of(st.none(), st.sampled_from(Role)),
    event=EVENTS,
)
def test_invalid_transitions_raise_and_never_return(
    state: ConversationState, role: Role | None, event: ConversationEvent
) -> None:
    profile = at(state, role=role, **CONSENTED)
    if type(event) in ConversationMachine.allowed_events(state, role):
        return
    with pytest.raises(InvalidTransition, match=f"{type(event).__name__} is not allowed in"):
        ConversationMachine.transition(profile, 1, event, NOW)


@given(events=st.lists(EVENTS, max_size=20), learners=st.integers(0, 3))
def test_transitions_are_deterministic(events: list[ConversationEvent], learners: int) -> None:
    journey = walk(events)
    for event in events[:3]:
        if type(event) in ConversationMachine.allowed_events(
            journey.profile.state, journey.profile.role
        ):
            first = ConversationMachine.transition(journey.profile, learners, event, NOW)
            second = ConversationMachine.transition(journey.profile, learners, event, NOW)
            assert first == second


@given(
    consented=st.booleans(),
    role=st.one_of(st.none(), st.sampled_from(Role)),
    guardian=st.booleans(),
    grade=st.one_of(st.none(), st.integers(1, 12)),
    learners=st.integers(0, 3),
)
def test_resume_state_is_active_only_with_consent_and_a_complete_profile(
    *, consented: bool, role: Role | None, guardian: bool, grade: int | None, learners: int
) -> None:
    profile = at(
        S.AWAITING_DELETION_CONFIRM,
        consented_at=NOW if consented else None,
        role=role,
        guardian_confirmed=guardian,
        grade=grade,
        subject="Maths",
        district="Barmer",
    )
    resumed = ConversationMachine.resume_state(profile, learners)
    if resumed is S.ACTIVE:
        assert consented
        assert role is not None
        if role is Role.PARENT:
            assert learners >= 1
        if role is Role.STUDENT:
            assert guardian
            assert grade is not None
