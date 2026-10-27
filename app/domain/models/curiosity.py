"""What a child engaged with, for the young-learner trajectory (s13 §4.4). Never a label."""

from typing import Literal

from pydantic import Field

from app.domain.enums import CuriosityDomain
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


type PostTurnTask = ExtractSignals  # S12 adds UpdateMemory; s10b MakeKhojCard
