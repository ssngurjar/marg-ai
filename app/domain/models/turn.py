"""A turn and what it knows about the user (contracts.md §2.2; s04 §4.4, §4.5)."""

from dataclasses import dataclass
from datetime import datetime

from app.domain.enums import Channel, ConversationState, Route
from app.domain.models.base import DomainModel, TurnId, UserHash
from app.domain.models.message import InboundMessage


class UserProfile(DomainModel):
    """The user as a turn sees them. S8 adds role, grade, language and the onboarding fields."""

    user_hash: UserHash
    channel: Channel
    state: ConversationState
    last_inbound_at: datetime | None  # WhatsApp's 24-hour window


class Exchange(DomainModel):
    """One earlier completed turn, for the model's context window."""

    user_text: str
    reply_text: str
    route: Route
    at: datetime


class TurnContext(DomainModel):
    """Everything one turn needs, loaded by the worker (s04 §4.5) and read by every step.

    S8 adds learners, S10b the active learner, open activity and child session, S12 memory and
    the roadmap, each with the table it reads.
    """

    turn_id: TurnId
    profile: UserProfile
    messages: list[InboundMessage]  # oldest first; at least one
    recent_exchanges: list[Exchange]  # the last RECENT_EXCHANGES, oldest first
    is_session_start: bool  # first turn, or SESSION_GAP since the previous (SessionRules)


@dataclass(frozen=True, slots=True)
class QueuedMessage:
    """A pending inbox row: the message, its row id and how many turns have tried it."""

    inbox_id: int
    message: InboundMessage
    attempts: int
