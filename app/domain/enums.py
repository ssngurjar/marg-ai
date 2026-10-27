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


class Language(StrEnum):
    HINDI = "hindi"
    HINGLISH = "hinglish"
    ENGLISH = "english"


class Route(StrEnum):
    ONBOARDING = "onboarding"
    EXPOSURE = "exposure"
    MENTOR = "mentor"
    ROADMAP = "roadmap"
    JOURNEY = "journey"
    CRISIS = "crisis"
    REFUSE = "refuse"
    OFF_TOPIC = "off_topic"
    DATA_DELETION = "data_deletion"
    REPEAT_PLEASE = "repeat_please"
    DASHBOARD_LINK = "dashboard_link"
    NUDGE = "nudge"
    KHOJ_CARD = "khoj_card"
    CHILD_TALK = "child_talk"


class StepName(StrEnum):
    FETCH_MEDIA = "fetch_media"
    TRANSCRIBE = "transcribe"
    SAFETY_IN = "safety_in"
    ROUTE = "route"
    GENERATE = "generate"
    TRANSLATE = "translate"
    SAFETY_OUT = "safety_out"
    SYNTHESIZE = "synthesize"
    ENQUEUE_REPLY = "enqueue_reply"
    EXTRACT_SIGNALS = "extract_signals"
    UPDATE_MEMORY = "update_memory"
    FETCH_IMAGE = "fetch_image"
    ANALYZE_IMAGE = "analyze_image"
    MAKE_CARD = "make_card"


class StepOutcome(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    FAILED = "failed"
    SKIPPED = "skipped"


class FailureKind(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    INVALID_RESPONSE = "invalid_response"
    EMPTY_INPUT = "empty_input"
    UNSUPPORTED_INPUT = "unsupported_input"
    BUDGET_EXCEEDED = "budget_exceeded"
    INTERNAL = "internal"


class TurnStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SafetyDecision(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    CRISIS = "crisis"


class SafetyCategory(StrEnum):
    """Llama Guard 4 / MLCommons hazards (s1 to s14) and our domain policy categories (d1 to d8)."""

    VIOLENT_CRIMES = "s1"
    NON_VIOLENT_CRIMES = "s2"
    SEX_CRIMES = "s3"
    CHILD_EXPLOITATION = "s4"
    DEFAMATION = "s5"
    SPECIALIZED_ADVICE = "s6"
    PRIVACY = "s7"
    INTELLECTUAL_PROPERTY = "s8"
    INDISCRIMINATE_WEAPONS = "s9"
    HATE = "s10"
    SELF_HARM = "s11"
    SEXUAL_CONTENT = "s12"
    ELECTIONS = "s13"
    CODE_INTERPRETER_ABUSE = "s14"
    MINOR_PII = "d1"
    GUARANTEE_PROMISE = "d2"
    ROMANTIC = "d3"
    MEDICAL = "d4"
    ABUSE_DISCLOSURE = "d5"
    PROMPT_LEAK = "d6"
    CHILD_PHYSICAL_HAZARD = "d7"
    CHILD_MANIPULATION = "d8"


class FixedReplyKind(StrEnum):
    CRISIS = "crisis"
    HOLDING = "holding"
    REPEAT_PLEASE = "repeat_please"
    TRY_AGAIN_LATER = "try_again_later"
    TOO_LONG = "too_long"
    UNSUPPORTED_MEDIA = "unsupported_media"
    REFUSE = "refuse"
    ONBOARDING = "onboarding"
    CONSENT_DECLINED = "consent_declined"
    DATA_DELETED = "data_deleted"
    ASK_CHAPTER = "ask_chapter"
    NUDGE = "nudge"
    PHOTO_HAS_PERSON = "photo_has_person"
    PHOTO_NOT_NEEDED = "photo_not_needed"
    CHILD_TALK_NOT_ENABLED = "child_talk_not_enabled"
    CHILD_TALK_COOLDOWN = "child_talk_cooldown"
    CHILD_SESSION_END = "child_session_end"
