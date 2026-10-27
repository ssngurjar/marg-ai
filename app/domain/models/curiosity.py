"""What a child engaged with, for the young-learner trajectory (s13 §4.4). Never a label."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.domain.enums import CuriosityDomain, Language
from app.domain.models.base import DomainModel, TurnId
from app.domain.models.learner import LearnerId

type CuriositySourceKind = Literal["parent_report", "child_words", "relayed_question"]


class CuriositySignals(DomainModel):
    """Domains the child went into, how engaged they were (0-3), and whether they asked their
    own question: the single most important early-curiosity signal."""

    domains: list[CuriosityDomain] = Field(max_length=3)
    engagement: int = Field(ge=0, le=3)
    child_asked_question: bool


class CuriositySource(DomainModel):
    """Set by a layer when its turn tells something about a child's curiosity (s13 §4.2)."""

    learner_id: LearnerId
    kind: CuriositySourceKind
    hint_domains: list[CuriosityDomain]  # the activity's own domains, when there is one
    activity_title: str | None
    activity_id: str | None = None  # the catalogue activity, for a khoj card's scene


class ExtractSignals(DomainModel):
    """Post-turn task (contracts §2.4): extract curiosity signals after the reply is sent, off
    the critical path. `user_text` is what the parent reported or the child said."""

    kind: Literal["extract_signals"] = "extract_signals"
    signal: Literal["curiosity"] = "curiosity"
    turn_id: TurnId
    learner_id: LearnerId
    user_text: str
    source: CuriositySource
    child_age: int | None  # None when the child's birth year isn't known


class MakeKhojCard(DomainModel):
    """Post-turn task (s10b §4.13, C6): an illustrated card of the child's discovery, after the
    reflection is delivered. Made only if the same turn's signals show engagement of 2 or more,
    and at most once per child per day."""

    kind: Literal["make_khoj_card"] = "make_khoj_card"
    turn_id: TurnId
    learner_id: LearnerId
    learner_activity_id: UUID
    activity_id: str
    activity_title: str
    domains: list[CuriosityDomain]
    child_nickname: str | None
    summary: str  # the reflection's neutral summary of what the child did
    reply_register: Language


type PostTurnTask = Annotated[ExtractSignals | MakeKhojCard, Field(discriminator="kind")]
