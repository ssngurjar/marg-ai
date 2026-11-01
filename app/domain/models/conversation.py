"""The onboarding conversation's events and effects (s08 §4.2). Pure data.

Events are what a message meant (decided by the onboarding layer); effects are what a transition
asks for, as data: the domain never does I/O. Both unions are closed, and the state machine
(`ConversationMachine`) maps (state, event) to a new profile and effects.
"""

from dataclasses import dataclass

from app.core.errors import InvalidProfileValue
from app.domain.enums import ConsentEventKind, CopyKey, Language, LearnerRelation, Role
from app.domain.models.district import LgdDistrict
from app.domain.models.learner import LearnerId
from app.domain.models.turn import UserProfile

GRADE_RANGE = range(1, 13)
GRADUATE = 13  # a student past class 12: a graduate or in college (field test, 2026-11-01)
STUDENT_LEVELS = range(1, GRADUATE + 1)
SUBJECT_MAX_CHARS = 40
DISTRICT_LENGTHS = range(2, 81)  # LGD's longest "district, state" label is 68
NICKNAME_MAX_CHARS = 20
MIN_CHILDREN_IN_ONE_ANSWER = 2  # ChildrenAnswered: one child is a ChildAnswered


@dataclass(frozen=True, slots=True)
class ProfileUpdate:
    """Only the fields present in an answer; each is validated on construction."""

    grade: int | None = None
    subject: str | None = None
    district: str | None = None

    def __post_init__(self) -> None:
        if self.grade is not None and self.grade not in STUDENT_LEVELS:
            raise InvalidProfileValue(f"grade {self.grade} is outside 1-12 (or 13, a graduate)")
        if self.subject is not None and not 1 <= len(self.subject.strip()) <= SUBJECT_MAX_CHARS:
            raise InvalidProfileValue(f"subject must be 1-{SUBJECT_MAX_CHARS} characters")
        if self.district is not None:
            district = self.district.strip()
            if len(district) not in DISTRICT_LENGTHS or not any(c.isalpha() for c in district):
                raise InvalidProfileValue("district must be 2-80 characters with a letter")

    @property
    def is_empty(self) -> bool:
        return self.grade is None and self.subject is None and self.district is None


# --- events ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FirstContact:
    detected_language: Language | None
    pending_question: str | None


@dataclass(frozen=True, slots=True)
class ConsentGiven:
    pass


@dataclass(frozen=True, slots=True)
class ConsentDeclined:
    pass


@dataclass(frozen=True, slots=True)
class RoleChosen:
    role: Role


@dataclass(frozen=True, slots=True)
class RoleUnavailable:
    """The user named a role the MVP doesn't offer yet (students, mvp-scope §4.4)."""

    role: Role


@dataclass(frozen=True, slots=True)
class GuardianConfirmed:
    pass


@dataclass(frozen=True, slots=True)
class GuardianDeclined:
    pass


@dataclass(frozen=True, slots=True)
class ProfileAnswered:
    update: ProfileUpdate
    # A question or a teacher's chapter in the same message ("kal class 8 mein bal aur dabav
    # padhana hai"): kept and answered once the profile is complete (owner, 2026-10-31).
    question: str | None = None


@dataclass(frozen=True, slots=True)
class ChildAnswered:
    """Validated against today's year by the state machine (age 2-19)."""

    birth_year: int
    nickname: str | None

    def __post_init__(self) -> None:
        if self.nickname is not None:
            nickname = self.nickname.strip()
            if not 1 <= len(nickname) <= NICKNAME_MAX_CHARS or not any(
                c.isalpha() for c in nickname
            ):
                raise InvalidProfileValue(f"nickname must be 1-{NICKNAME_MAX_CHARS} characters")


@dataclass(frozen=True, slots=True)
class ChildNamed:
    """A child's home name given without the age ("pinku hai naam"): kept in the reply and asked
    for the age (owner's field test, 2026-11-01: three names got "samajh nahi aaya")."""

    nickname: str

    def __post_init__(self) -> None:
        nickname = self.nickname.strip()
        if not 1 <= len(nickname) <= NICKNAME_MAX_CHARS or not any(c.isalpha() for c in nickname):
            raise InvalidProfileValue(f"nickname must be 1-{NICKNAME_MAX_CHARS} characters")


@dataclass(frozen=True, slots=True)
class DistrictUnclear:
    """A district answer LGD's list doesn't settle (critic review D4, 2026-11-01): names to
    confirm, a state named alone, or nothing found. Nothing is stored."""

    candidates: tuple[LgdDistrict, ...]
    state_named: str | None = None


@dataclass(frozen=True, slots=True)
class ChildrenAnswered:
    """Two or more children in one answer ("Munni 5 aur Golu 7"), in the order given: each is
    added, up to the limit, and asked about on its own (critic review D3, 2026-11-01)."""

    children: tuple[ChildAnswered, ...]

    def __post_init__(self) -> None:
        if len(self.children) < MIN_CHILDREN_IN_ONE_ANSWER:
            raise InvalidProfileValue("ChildrenAnswered needs at least two children")


@dataclass(frozen=True, slots=True)
class ChildInvalid:
    reason: CopyKey  # CHILD_INVALID_AGE or CHILD_NICKNAME_TOO_LONG: the precise re-ask


@dataclass(frozen=True, slots=True)
class AddChild:
    pass


@dataclass(frozen=True, slots=True)
class ChildTalkAnswered:
    learner_id: LearnerId
    allowed: bool


@dataclass(frozen=True, slots=True)
class TeacherAsked:
    """An active teacher's message before the teacher feature exists (owner, 2026-10-27)."""


@dataclass(frozen=True, slots=True)
class LanguageSwitched:
    language: Language


@dataclass(frozen=True, slots=True)
class QuestionNoted:
    question: str


@dataclass(frozen=True, slots=True)
class AboutMargAsked:
    """A question about Marg itself during onboarding ("what can you do?", "why do you need
    this?"): answered at once, then the waiting question again (owner, 2026-11-01). `braj`: it
    asks whether Marg speaks Braj (owner's field test, 2026-11-01)."""

    braj: bool = False


@dataclass(frozen=True, slots=True)
class Unrecognised:
    not_understood: CopyKey = CopyKey.NOT_UNDERSTOOD  # INVALID_GRADE for a grade outside 1-12
    # Only a greeting ("Hi" again, after a reload): ask the waiting question again, without
    # "Sorry, I didn't understand" (owner's judge walkthrough, 2026-10-29).
    greeted: bool = False


@dataclass(frozen=True, slots=True)
class DeletionRequested:
    pass


@dataclass(frozen=True, slots=True)
class DeletionConfirmed:
    pass


@dataclass(frozen=True, slots=True)
class DeletionCancelled:
    pass


type ConversationEvent = (
    FirstContact
    | ConsentGiven
    | ConsentDeclined
    | RoleChosen
    | RoleUnavailable
    | GuardianConfirmed
    | GuardianDeclined
    | ProfileAnswered
    | ChildAnswered
    | ChildrenAnswered
    | ChildInvalid
    | ChildNamed
    | DistrictUnclear
    | AddChild
    | ChildTalkAnswered
    | TeacherAsked
    | LanguageSwitched
    | QuestionNoted
    | AboutMargAsked
    | Unrecognised
    | DeletionRequested
    | DeletionConfirmed
    | DeletionCancelled
)


# --- effects -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SendCopy:
    key: CopyKey


@dataclass(frozen=True, slots=True)
class RecordConsent:
    kind: ConsentEventKind


@dataclass(frozen=True, slots=True)
class UpsertLearner:
    relation: LearnerRelation
    birth_year: int
    nickname: str | None


@dataclass(frozen=True, slots=True)
class SetChildTalk:
    learner_id: LearnerId
    granted: bool


@dataclass(frozen=True, slots=True)
class PurgeAfterDelivery:
    pass


@dataclass(frozen=True, slots=True)
class HandoffPendingQuestion:
    question: str


@dataclass(frozen=True, slots=True)
class HandoffFirstKhoj:
    """The learner created in this transition gets today's khoj in the same turn (s10b)."""


type Effect = (
    SendCopy
    | RecordConsent
    | UpsertLearner
    | SetChildTalk
    | PurgeAfterDelivery
    | HandoffPendingQuestion
    | HandoffFirstKhoj
)


@dataclass(frozen=True, slots=True)
class Transition:
    profile: UserProfile  # state, fields and pending question after the event
    effects: tuple[Effect, ...]
