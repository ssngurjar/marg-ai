"""Learners: the child or student whose journey Marg.ai follows (contracts §2.2, data-model)."""

from datetime import datetime
from typing import NewType
from uuid import UUID

from app.domain.enums import LearnerRelation
from app.domain.models.base import DomainModel

LearnerId = NewType("LearnerId", UUID)


class Learner(DomainModel):
    """Only a nickname (≤ 20 chars, never a full name) and a birth year are ever kept."""

    id: LearnerId
    relation: LearnerRelation
    nickname: str | None
    birth_year: int
    child_talk_consented_at: datetime | None  # C13: the parent's consent; None = child talk off
