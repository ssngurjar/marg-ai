"""A child talking to Marg.ai directly on the parent's phone (s10b §4.16, C13)."""

from datetime import datetime, timedelta
from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.domain.enums import ChildSessionEndReason, CuriosityDomain, DailyTalkLimit, Language
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


class ChildSessionSpan(DomainModel):
    """When one of a child's sessions ran, for the daily limit: its start, its end and why it
    ended (both None while open), when its last question was answered (None: none yet, or the
    session predates the record) and how many were. Never what was said."""

    learner_id: LearnerId
    started_at: AwareDatetime
    ended_at: AwareDatetime | None
    end_reason: ChildSessionEndReason | None
    last_answered_at: AwareDatetime | None
    turns_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.ended_at is None) != (self.end_reason is None):
            raise ValueError("a child session has an end time exactly when it has an end reason")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("a child session can't end before it starts")
        if self.last_answered_at is not None and self.last_answered_at < self.started_at:
            raise ValueError("a child session can't answer before it starts")
        return self


class DailyTalkTime(DomainModel):
    """How long a child talked with Marg on one day, and their daily limit: what the parent's
    summary reports (owner, 2026-11-13)."""

    used: timedelta = Field(ge=timedelta(0))
    limit: DailyTalkLimit
