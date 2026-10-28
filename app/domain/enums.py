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


class AudioVerdict(StrEnum):
    """Whether a voice note is worth transcribing (s06 §4.4)."""

    OK = "ok"
    TOO_SHORT = "too_short"
    SILENT = "silent"
    TOO_LONG = "too_long"


class Speaker(StrEnum):
    """Who is talking this turn (C13): the adult, or a child inside a child-talk session."""

    GUIDE = "guide"
    LEARNER = "learner"


class ChildSessionEndReason(StrEnum):
    TURN_LIMIT = "turn_limit"
    TIME_LIMIT = "time_limit"
    CHILD_ENDED = "child_ended"
    CRISIS = "crisis"
    EXPIRED = "expired"  # the child stopped mid-session; closed by maintenance


class MediaPurpose(StrEnum):
    """Why a media_blobs row exists; each purpose has its own expiry (data-model `media_blobs`)."""

    INBOUND_AUDIO = "inbound_audio"
    INBOUND_PHOTO = "inbound_photo"  # a web visitor's photo, only until its turn has looked at it
    REPLY_AUDIO = "reply_audio"
    KHOJ_CARD = "khoj_card"


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


class FixedReplyVariant(StrEnum):
    """Which version of a fixed reply: DEFAULT for every kind, plus REFUSE and CRISIS variants."""

    DEFAULT = "default"
    HARMFUL = "harmful"
    PRIVACY = "privacy"
    MEDICAL = "medical"
    GENERAL = "general"
    GENERIC = "generic"
    SELF_HARM = "self_harm"
    ABUSE = "abuse"


class Mode(StrEnum):
    EXPOSURE = "exposure"
    MENTOR = "mentor"
    ROADMAP = "roadmap"
    JOURNEY = "journey"


class Role(StrEnum):
    """Who the user is (s08). The MVP offers PARENT and TEACHER; STUDENT is Phase 2."""

    STUDENT = "student"
    TEACHER = "teacher"
    PARENT = "parent"


class ConsentEventKind(StrEnum):
    GRANTED = "granted"
    GUARDIAN_CONFIRMED = "guardian_confirmed"
    CHILD_PROFILE_CONSENT = "child_profile_consent"
    CHILD_TALK_CONSENT = "child_talk_consent"
    REVOKED = "revoked"  # reserved (s08 Q3): withdrawing consent is a deletion
    DELETION_REQUESTED = "deletion_requested"


class LearnerRelation(StrEnum):
    """How the user relates to the learner."""

    SELF = "self"  # a student's own learner
    PARENT = "parent"  # a parent's child


class CopyKey(StrEnum):
    """Fixed onboarding copy (s08 §4.8; text in app/constants/onboarding_copy.py). Not persisted."""

    INTRO_CONSENT = "intro_consent"
    INTRO_CONSENT_WITH_QUESTION = "intro_consent_with_question"
    CONSENT_DECLINED = "consent_declined"
    ASK_ROLE = "ask_role"
    STUDENT_COMING_SOON = "student_coming_soon"
    ASK_GUARDIAN = "ask_guardian"
    GUARDIAN_NEEDED = "guardian_needed"
    ASK_GRADE_STUDENT = "ask_grade_student"
    ASK_SUBJECT_TEACHER = "ask_subject_teacher"
    ASK_GRADE_TEACHER = "ask_grade_teacher"
    ASK_DISTRICT = "ask_district"
    INVALID_GRADE = "invalid_grade"
    ASK_CHILD = "ask_child"
    CHILD_INVALID_AGE = "child_invalid_age"
    CHILD_NICKNAME_TOO_LONG = "child_nickname_too_long"
    MAX_CHILDREN = "max_children"
    QUESTION_NOTED = "question_noted"
    NOT_UNDERSTOOD = "not_understood"
    PROFILE_DONE = "profile_done"
    PROFILE_DONE_TEACHER = "profile_done_teacher"
    PROFILE_DONE_PARENT = "profile_done_parent"
    ASK_CHILD_TALK = "ask_child_talk"
    CHILD_TALK_ENABLED = "child_talk_enabled"
    CHILD_TALK_OFF = "child_talk_off"
    TEACHER_WAITING = "teacher_waiting"
    LANGUAGE_CHANGED = "language_changed"
    CONFIRM_DELETE = "confirm_delete"
    DELETE_CANCELLED = "delete_cancelled"
    DATA_DELETED = "data_deleted"


class CuriosityDomain(StrEnum):
    """What a child explores (s10b §4.3, s13). Tags on activities and curiosity signals."""

    NATURE_LIVING = "nature_living"
    EARTH_SKY = "earth_sky"
    NUMBERS_PATTERNS = "numbers_patterns"
    WORDS_STORIES = "words_stories"
    MAKING_BUILDING = "making_building"
    MOVEMENT_BODY = "movement_body"
    ART_MUSIC = "art_music"
    PEOPLE_FEELINGS = "people_feelings"
    EVERYDAY_WORK = "everyday_work"


class ActivityStatus(StrEnum):
    OFFERED = "offered"
    DONE = "done"
    SKIPPED = "skipped"


class AgeBand(StrEnum):
    """NEP 5+3+3+4 stages by age (s10b §4.2). The MVP serves FOUNDATIONAL_3_8."""

    UNDER_3 = "under_3"
    FOUNDATIONAL_3_8 = "foundational_3_8"
    PREPARATORY_8_11 = "preparatory_8_11"
    MIDDLE_11_14 = "middle_11_14"
    SECONDARY_14_18 = "secondary_14_18"
    ADULT = "adult"


class EmbedPurpose(StrEnum):
    """What a text is embedded as (s11 §4.4): e5 needs "query: " or "passage: " in front."""

    QUERY = "query"
    PASSAGE = "passage"


class CorpusTopic(StrEnum):
    """The corpus folders (s11 §4.1); a document's topic must equal its folder."""

    EXAMS = "exams"
    SCHOLARSHIPS = "scholarships"
    SPORTS = "sports"
    ENTREPRENEURSHIP = "entrepreneurship"
    PUBLIC_SERVICE = "public_service"
    SKILLING = "skilling"
    EXPOSURE_FIELDS = "exposure_fields"


class RoadmapStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class RoadmapStepStatus(StrEnum):
    TODO = "todo"
    DONE = "done"
    SKIPPED = "skipped"
