"""GoldenCase: one hand-written eval case from `evals/golden/*.yaml` (s15 §4.1).

A case sets up a user (a profile, children, an activity already offered), plays one or more
messages through the real pipeline, and says what must be true of the last reply (and, when a
turn carries its own `expect`, of that turn's reply). Expectations describe behaviour, never
facts: a source is the authority for an amount or a date, never this file.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import FixedReplyKind, Language, LearnerRelation, Role, Route

DEFERRED_TAG = "deferred"  # loaded and runnable, excluded from the pass rate (decision B9)
EXPECTS_FAILURE_TAG = "expects_failure"  # a failed step is the point of the case


class _CaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GoldenProfile(_CaseModel):
    """Seeded straight to ACTIVE with consent (and the guardian's, for students)."""

    role: Role
    grade: int | None = Field(default=None, ge=1, le=12)
    subject: str | None = None
    district: str | None = None
    language: Language

    @model_validator(mode="after")
    def _students_and_teachers_have_a_class(self) -> Self:
        if self.role in {Role.STUDENT, Role.TEACHER} and (self.grade is None or not self.district):
            raise ValueError(f"a {self.role.value} profile needs grade and district")
        return self


class GoldenLearner(_CaseModel):
    relation: LearnerRelation
    nickname: str | None = Field(default=None, max_length=20)
    age: int = Field(ge=2, le=19)  # birth_year = the run's year minus age


class GoldenAttachment(_CaseModel):
    kind: Literal["image"]
    fixture: str = Field(min_length=1)  # a file in evals/fixtures/images/


class TurnExpectation(_CaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    route: Route | None = None
    # `register` in the files; pydantic reserves the name (as LocalisedReply.reply_register)
    reply_register: Language | None = Field(default=None, alias="register")
    safety: Literal["pass", "block_in", "block_out"] | None = None
    fixed_reply: FixedReplyKind | None = None
    citations: Literal["required", "forbidden", "any"] = "any"
    photo_count: dict[str, int] | None = None  # phrase → count, within one either way
    card: Literal["sent", "none"] | None = None
    must: list[str] = []
    must_not: list[str] = []

    @property
    def judged_items(self) -> list[str]:
        return [*self.must, *self.must_not]


class GoldenTurn(_CaseModel):
    user: str  # as typed, or what a voice note would say
    button: str | None = None  # an interactive reply id instead of text
    audio_fixture: str | None = None  # tests/fixtures/audio/<file>: plays through real STT
    expect: TurnExpectation | None = None


class GoldenCase(_CaseModel):
    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*-\d{3}$")
    title: str = Field(min_length=1)
    tags: list[str] = []
    profile: GoldenProfile | None = None  # None: a brand-new user (NEW)
    learner: GoldenLearner | None = None
    learners: list[GoldenLearner] = []
    open_activity: str | None = None  # a catalogue id, seeded as OFFERED for the first child
    child_talk_consent: bool | None = None  # the parent's one-time consent for child talk
    speaker: Literal["guide", "learner"] = "guide"  # learner: the child is talking (C13)
    attachments: list[GoldenAttachment] = []  # sent with the first turn
    turns: list[GoldenTurn] = Field(min_length=1)
    expect: TurnExpectation  # checked after the last turn

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.learner is not None and self.learners:
            raise ValueError("learner and learners are mutually exclusive")
        children = self.children
        if children and (
            self.profile is None or self.profile.role not in {Role.PARENT, Role.STUDENT}
        ):
            raise ValueError("children need a parent profile (or a student's self learner)")
        if (self.open_activity or self.child_talk_consent is not None) and not children:
            raise ValueError("open_activity and child_talk_consent need a learner")
        if not self.expect.must and self.expect.fixed_reply is None:
            raise ValueError("expect.must is empty and no fixed_reply is expected")
        return self

    @property
    def children(self) -> list[GoldenLearner]:
        return [self.learner] if self.learner is not None else list(self.learners)

    @property
    def deferred(self) -> bool:
        return DEFERRED_TAG in self.tags
