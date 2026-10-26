"""Closed sets of values shared across the app (contracts.md §1).

Values are persisted, so they're never renamed; a new value means a migration that updates the
matching CHECK constraint. Enums are added here by the step that first uses them.
"""

from enum import StrEnum


class Channel(StrEnum):
    WHATSAPP = "whatsapp"
    WEB = "web"


class MessageKind(StrEnum):
    TEXT = "text"
    AUDIO = "audio"
    IMAGE = "image"
    INTERACTIVE = "interactive"
    UNSUPPORTED = "unsupported"


class ConversationState(StrEnum):
    NEW = "new"
    AWAITING_CONSENT = "awaiting_consent"
    AWAITING_ROLE = "awaiting_role"
    AWAITING_GUARDIAN = "awaiting_guardian"
    AWAITING_CHILD = "awaiting_child"
    AWAITING_PROFILE = "awaiting_profile"
    ACTIVE = "active"
    AWAITING_DELETION_CONFIRM = "awaiting_deletion_confirm"


class InboxStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class PartKind(StrEnum):
    TEXT = "text"
    AUDIO = "audio"
    IMAGE = "image"
    INTERACTIVE = "interactive"
    TEMPLATE = "template"
