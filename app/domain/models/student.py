"""A student's plan and what Marg remembers about them (s12 §4.4, §4.7; contracts §2.2)."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import Field, HttpUrl, StringConstraints

from app.domain.enums import RoadmapStatus, RoadmapStepStatus
from app.domain.models.base import DomainModel


class RoadmapStep(DomainModel):
    position: int = Field(ge=1)
    action: str
    timeframe: str
    cost_inr: Decimal | None  # a cost is a fact: only with a source
    source_url: HttpUrl | None
    status: RoadmapStepStatus


class Roadmap(DomainModel):
    """A student's active plan: 3-6 concrete steps toward one goal."""

    id: UUID
    goal: str
    status: RoadmapStatus
    steps: list[RoadmapStep]
    created_at: datetime


class ProfileMemory(DomainModel):
    """A short rolling summary of what the student told us about themselves (no sources)."""

    summary: str = Field(max_length=600)
    ambitions: list[str] = Field(max_length=5)
    constraints: list[str] = Field(max_length=5)
    updated_at: datetime


type MemoryItem = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)
]


class MemoryUpdate(DomainModel):
    """The memory model's output (strict schema): what is still true, plus what is new."""

    summary: str = Field(max_length=600)  # third person, facts the student told us, no names
    ambitions: list[MemoryItem] = Field(max_length=5)  # "doctor (NEET)", "kabaddi at state level"
    constraints: list[MemoryItem] = Field(max_length=5)  # "family money is tight"
