"""A child talking to Marg.ai directly on the parent's phone (s10b §4.16, C13)."""

from datetime import datetime
from uuid import UUID

from app.domain.enums import CuriosityDomain, Language
from app.domain.models.base import DomainModel
from app.domain.models.learner import LearnerId


class ChildSession(DomainModel):
    """An open session: the child's turns so far and what they asked about (topics, never
    their words)."""

    id: UUID
    learner_id: LearnerId
    started_at: datetime
    turns_count: int
    topics: list[CuriosityDomain]
    language: Language | None = None  # what the child asked for ("Hindi"); None: not asked
