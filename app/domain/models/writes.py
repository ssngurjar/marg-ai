"""State changes that commit with the reply (contracts §2.4).

Layers never write to the database: they return `TurnWrite`s, and the worker applies them, in
list order, in the same transaction as the outbox rows. Variants arrive with the step that builds
what they change.
"""

from datetime import datetime, time
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.domain.enums import (
    ActivityStatus,
    ChildSessionEndReason,
    ConsentEventKind,
    ConversationState,
    CuriosityDomain,
    Language,
    LearnerRelation,
    Role,
)
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


class ActivityOffered(DomainModel):
    """s10b: an activity was sent for a learner. The id is chosen by the layer, so a later write
    in the same turn could refer to it."""

    kind: Literal["activity_offered"] = "activity_offered"
    learner_activity_id: UUID
    learner_id: LearnerId
    activity_id: str
    activity_version: int


class ActivityReported(DomainModel):
    """s10b: the parent reported back (DONE, with a neutral ≤ 200-char summary) or skipped it."""

    kind: Literal["activity_reported"] = "activity_reported"
    learner_activity_id: UUID
    status: ActivityStatus
    summary: str | None = Field(max_length=200)


class ChildSessionStart(DomainModel):
    """s10b (C13): the child started talking. The id is chosen by the layer, so this turn's
    ChildTalkTurn can refer to it."""

    kind: Literal["child_session_start"] = "child_session_start"
    session_id: UUID
    learner_id: LearnerId


class ChildTalkTurn(DomainModel):
    """s10b (C13): one answered child turn: counts toward the limit and records the topic (a
    curiosity domain, never the child's words) for the parent's summary."""

    kind: Literal["child_talk_turn"] = "child_talk_turn"
    session_id: UUID
    topic: CuriosityDomain | None


class ChildSessionEnd(DomainModel):
    """s10b (C13): the session ended (limit, goodbye, crisis)."""

    kind: Literal["child_session_end"] = "child_session_end"
    session_id: UUID
    reason: ChildSessionEndReason


class NudgePreference(DomainModel):
    """s10b: the parent turned the daily khoj message on at a time (IST), or off."""

    kind: Literal["nudge_preference"] = "nudge_preference"
    enabled: bool
    local_time: time | None  # IST; None when turning off


class DeleteInboundMedia(DomainModel):
    """s06: a web voice note this turn has heard; deleted with the reply (raw audio isn't kept
    after transcription, CLAUDE.md §11)."""

    kind: Literal["delete_inbound_media"] = "delete_inbound_media"
    blob_id: UUID


type TurnWrite = Annotated[
    ProfileChange
    | LearnerUpsert
    | MarkPurgeAfterDelivery
    | ChildTalkConsent
    | ActivityOffered
    | ActivityReported
    | ChildSessionStart
    | ChildTalkTurn
    | ChildSessionEnd
    | NudgePreference
    | DeleteInboundMedia,
    Field(discriminator="kind"),
]
