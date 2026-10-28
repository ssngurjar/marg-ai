"""Activities: reviewed catalogue entries and what was offered to a learner (s10b §4.3, §5)."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.domain.enums import ActivityStatus, CuriosityDomain
from app.domain.models.base import DomainModel
from app.domain.models.learner import LearnerId

type Setting = Literal["home", "kitchen", "outdoors", "field", "market", "courtyard"]
type Season = Literal["any", "summer", "monsoon", "winter"]


class Activity(DomainModel):
    """One khoj, as reviewed. Steps, questions and tips are English: the source the
    personalisation rewords for each family, never adding steps or materials."""

    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    version: int = Field(ge=1)
    status: Literal["draft", "enabled", "retired"]
    age_min: int
    age_max: int
    domains: list[CuriosityDomain] = Field(min_length=1, max_length=3)
    setting: Setting
    season: Season
    duration_minutes: int = Field(ge=1, le=30)
    materials: list[str]
    # What SAM 3.1 counts in a photo of the child's work (owner, 2026-10-28): reviewed with the
    # activity. Empty: a photo is welcomed but nothing is counted.
    photo_count_phrases: list[
        Annotated[str, StringConstraints(pattern=r"^[a-z]+( [a-z]+){0,2}$", max_length=40)]
    ] = Field(default_factory=list, max_length=3)
    title: str = Field(min_length=1, max_length=60)
    steps: list[str] = Field(min_length=1, max_length=6)
    questions_to_ask: list[str] = Field(min_length=2, max_length=4)
    listen_for: str = Field(min_length=1, max_length=200)
    parent_tips: list[str] = Field(min_length=1, max_length=3)
    hazards: list[str]
    safety_notes: list[str]
    reviewed_by_role: str | None
    reviewed_on: date | None


class OfferRecord(DomainModel):
    """An activity offered to a learner, as stored (learner_activities). The store doesn't know
    the catalogue, so the journey layer looks the activity up by id."""

    learner_activity_id: UUID
    learner_id: LearnerId
    activity_id: str
    activity_version: int
    offered_at: datetime
    status: ActivityStatus


class PastActivity(DomainModel):
    """An activity offered to a learner before, with its domains: what selection reads."""

    activity_id: str
    domains: list[CuriosityDomain]
    offered_at: datetime
    status: ActivityStatus


class OfferedActivity(DomainModel):
    """The open activity a parent may be reporting on (offered, not yet done, < 48 h)."""

    learner_activity_id: UUID
    learner_id: LearnerId
    activity: Activity
    offered_at: datetime
