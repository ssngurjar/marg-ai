"""The onboarding conversation's events and effects (s08 §4.2). Pure data.

Events are what a message meant (decided by the onboarding layer); effects are what a transition
asks for, as data: the domain never does I/O. Both unions are closed, and the state machine
(`ConversationMachine`) maps (state, event) to a new profile and effects.
"""

from dataclasses import dataclass

from app.core.errors import InvalidProfileValue
from app.domain.enums import ConsentEventKind, CopyKey, Language, LearnerRelation, Role
from app.domain.models.learner import LearnerId
from app.domain.models.turn import UserProfile

GRADE_RANGE = range(1, 13)
SUBJECT_MAX_CHARS = 40
DISTRICT_LENGTHS = range(2, 61)
NICKNAME_MAX_CHARS = 20


@dataclass(frozen=True, slots=True)
class ProfileUpdate:
    """Only the fields present in an answer; each is validated on construction."""

    grade: int | None = None
    subject: str | None = None
    district: str | None = None

    def __post_init__(self) -> None:
        if self.grade is not None and self.grade not in GRADE_RANGE:
            raise InvalidProfileValue(f"grade {self.grade} is outside 1-12")
        if self.subject is not None and not 1 <= len(self.subject.strip()) <= SUBJECT_MAX_CHARS:
            raise InvalidProfileValue(f"subject must be 1-{SUBJECT_MAX_CHARS} characters")
        if self.district is not None:
            district = self.district.strip()
            if len(district) not in DISTRICT_LENGTHS or not any(c.isalpha() for c in district):
                raise InvalidProfileValue("district must be 2-60 characters with a letter")

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
class Unrecognised:
    not_understood: CopyKey = CopyKey.NOT_UNDERSTOOD  # INVALID_GRADE for a grade outside 1-12


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
    | ChildInvalid
    | AddChild
    | ChildTalkAnswered
    | TeacherAsked
    | LanguageSwitched
    | QuestionNoted
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
