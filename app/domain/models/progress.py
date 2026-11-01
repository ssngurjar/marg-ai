"""What a parent can see of a child's progress (owner, 2026-11-01): counts and topics from the
record, never the child's words.
"""

from app.domain.enums import CuriosityDomain
from app.domain.models.base import DomainModel
from app.domain.models.learner import LearnerId


class ChildTalkTopics(DomainModel):
    """What a child asked Marg about in their own talks lately, by topic."""

    learner_id: LearnerId
    topics: list[CuriosityDomain]
