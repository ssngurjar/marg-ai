"""State changes that commit with the reply (contracts §2.4).

Layers never write to the database: they return `TurnWrite`s, and the worker applies them, in
list order, in the same transaction as the outbox rows. Variants arrive with the step that builds
what they change.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from app.domain.enums import ConsentEventKind, ConversationState, Language, LearnerRelation, Role
from app.domain.models.base import DomainModel
from app.domain.models.learner import LearnerId


class ProfileChange(DomainModel):
    """s08: the new state and the profile fields that changed. None means unchanged."""

    kind: Literal["profile_change"] = "profile_change"
    expected_state: ConversationState  # optimistic check: a mismatch raises LeaseLost
    new_state: ConversationState
    role: Role | None
    grade: int | None
    subject: str | None
    district: str | None
    language: Language | None
    guardian_confirmed: bool | None
    consented_at: datetime | None
    pending_question: str | None
    clear_pending_question: bool
    consent_events: list[ConsentEventKind]
    consent_prompt_version: str | None


class LearnerUpsert(DomainModel):
    """s08 / s10b: create a learner (its id is chosen by the layer, so a same-turn handoff can
    refer to it before anything commits)."""

    kind: Literal["learner_upsert"] = "learner_upsert"
    learner_id: LearnerId
    relation: LearnerRelation
    nickname: str | None
    birth_year: int


class MarkPurgeAfterDelivery(DomainModel):
    """s08: delete the user once this turn's last part has been delivered (decision B4)."""

    kind: Literal["mark_purge_after_delivery"] = "mark_purge_after_delivery"


class ChildTalkConsent(DomainModel):
    """s08 (C13): a parent grants or revokes direct child talk for one learner."""

    kind: Literal["child_talk_consent"] = "child_talk_consent"
    learner_id: LearnerId
    granted: bool


type TurnWrite = Annotated[
    ProfileChange | LearnerUpsert | MarkPurgeAfterDelivery | ChildTalkConsent,
    Field(discriminator="kind"),
]
