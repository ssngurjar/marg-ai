"""Table definitions (data-model.md). Each table is created by its step's Alembic migration.

Enum columns are text with a CHECK listing the StrEnum values, so Python and the database agree.
"""

from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    SmallInteger,
    Table,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID

from app.domain.enums import (
    ActivityStatus,
    Channel,
    ChildSessionEndReason,
    ConsentEventKind,
    ConversationState,
    CorpusTopic,
    FailureKind,
    FixedReplyKind,
    InboxStatus,
    Language,
    LearnerRelation,
    MediaPurpose,
    MessageKind,
    OutboxStatus,
    PartKind,
    RoadmapStatus,
    RoadmapStepStatus,
    Role,
    Route,
    SafetyDecision,
    Sentiment,
    StepName,
    StepOutcome,
    TurnStatus,
)

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


def allowed_values(column: str, values: type[StrEnum]) -> CheckConstraint:
    listed = ", ".join(f"'{member.value}'" for member in values)
    return CheckConstraint(f"{column} IN ({listed})", name=f"{column}_valid")


users = Table(
    "users",
    metadata,
    Column("user_hash", Text, primary_key=True),
    Column("channel", Text, nullable=False),
    Column("address_ciphertext", LargeBinary, nullable=True),
    Column("state", Text, nullable=False, server_default=ConversationState.NEW.value),
    Column("role", Text, nullable=True),  # S8
    Column("grade", SmallInteger, nullable=True),
    Column("subject", Text, nullable=True),
    Column("district", Text, nullable=True),
    Column("language", Text, nullable=True),
    Column("guardian_confirmed", Boolean, nullable=False, server_default=text("false")),
    Column("consented_at", DateTime(timezone=True), nullable=True),
    Column("pending_question", Text, nullable=True),  # personal data; cleared on handoff
    Column("purge_after_turn_id", UUID(as_uuid=True), nullable=True),
    Column("last_inbound_at", DateTime(timezone=True), nullable=True),
    Column("lease_owner", Text, nullable=True),  # the worker running this user's turn (s04 §4.3)
    Column("lease_expires_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("user_hash ~ '^[0-9a-f]{64}$'", name="user_hash_is_hex64"),
    CheckConstraint("grade BETWEEN 1 AND 12", name="grade_range"),
    allowed_values("channel", Channel),
    allowed_values("state", ConversationState),
    allowed_values("role", Role),
    allowed_values("language", Language),
    Index(
        None,
        "purge_after_turn_id",
        postgresql_where=text("purge_after_turn_id IS NOT NULL"),
    ),
    Index(None, "lease_expires_at", postgresql_where=text("lease_owner IS NOT NULL")),
)

consent_events = Table(
    "consent_events",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("user_hash", Text, ForeignKey("users.user_hash", ondelete="CASCADE"), nullable=False),
    Column("kind", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),  # COPY_VERSION of the consent text shown
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Index(None, "user_hash"),
    allowed_values("kind", ConsentEventKind),
)

learners = Table(
    "learners",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "owner_user_hash",
        Text,
        ForeignKey("users.user_hash", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("relation", Text, nullable=False),
    Column("nickname", Text, nullable=True),  # ≤ 20 chars; never a full name
    Column("birth_year", SmallInteger, nullable=False),
    Column("child_talk_consented_at", DateTime(timezone=True), nullable=True),  # C13
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("birth_year BETWEEN 2000 AND 2100", name="birth_year_sanity"),
    CheckConstraint("char_length(nickname) <= 20", name="nickname_length"),
    allowed_values("relation", LearnerRelation),
    Index(None, "owner_user_hash"),
    Index(
        "uq_learners_one_self_per_owner",
        "owner_user_hash",
        unique=True,
        postgresql_where=text("relation = 'self'"),
    ),
)

inbox_messages = Table(
    "inbox_messages",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("channel", Text, nullable=False),
    Column("external_id", Text, nullable=False),
    Column("user_hash", Text, ForeignKey("users.user_hash", ondelete="CASCADE"), nullable=False),
    Column("kind", Text, nullable=False),
    Column("text", Text, nullable=True),
    Column("media_provider_id", Text, nullable=True),
    # a web voice note (S14), deleted once its turn has heard it; WhatsApp media is never stored
    Column("media_blob_id", UUID(as_uuid=True), ForeignKey("media_blobs.id", ondelete="SET NULL")),
    Column("media_mime_type", Text, nullable=True),
    Column("interactive_reply_id", Text, nullable=True),
    Column("raw_payload", JSONB, nullable=True),
    Column("status", Text, nullable=False, server_default=InboxStatus.PENDING.value),
    # Added in S4: retries and which turn took the message
    Column("attempts", SmallInteger, nullable=False, server_default=text("0")),
    Column("available_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("turn_id", UUID(as_uuid=True), ForeignKey("turns.id", ondelete="SET NULL")),
    Column("provider_sent_at", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("channel", "external_id"),
    Index(None, "user_hash", "status"),
    Index(
        "ix_inbox_messages_pending_available_at",
        "status",
        "available_at",
        postgresql_where=text("status = 'pending'"),
    ),
    allowed_values("channel", Channel),
    allowed_values("kind", MessageKind),
    allowed_values("status", InboxStatus),
)


turns = Table(
    "turns",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_hash", Text, ForeignKey("users.user_hash", ondelete="CASCADE"), nullable=False),
    Column("status", Text, nullable=False),
    Column("route", Text, nullable=True),
    Column("user_text", Text, nullable=True),  # NULL for crisis turns; cleared after retention
    Column("reply_text", Text, nullable=True),
    Column("reply_register", Text, nullable=True),
    Column("fixed_reply_kind", Text, nullable=True),
    Column("prompt_versions", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("failure_step", Text, nullable=True),
    Column("failure_kind", Text, nullable=True),
    Column("worker_id", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Index("ix_turns_user_hash_started_at", "user_hash", text("started_at DESC")),
    Index(None, "started_at"),
    allowed_values("status", TurnStatus),
    allowed_values("route", Route),
    allowed_values("reply_register", Language),
    allowed_values("fixed_reply_kind", FixedReplyKind),
    allowed_values("failure_step", StepName),
    allowed_values("failure_kind", FailureKind),
)

turn_steps = Table(
    "turn_steps",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column(
        "turn_id", UUID(as_uuid=True), ForeignKey("turns.id", ondelete="CASCADE"), nullable=False
    ),
    Column("step", Text, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("failure_kind", Text, nullable=True),
    Column("decision", Text, nullable=True),  # safety_in / safety_out rows only
    Column("detail", Text, nullable=True),  # fixed vocabulary only, never user content
    Column("provider", Text, nullable=True),
    Column("model", Text, nullable=True),
    Column("input_tokens", Integer, nullable=True),
    Column("output_tokens", Integer, nullable=True),
    Column("audio_seconds", Numeric(10, 3), nullable=True),
    Column("cost_usd", Numeric(12, 6), nullable=False, server_default=text("0")),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("duration_ms", Integer, nullable=False),
    Index(None, "turn_id"),
    Index(None, "started_at"),
    allowed_values("step", StepName),
    allowed_values("outcome", StepOutcome),
    allowed_values("failure_kind", FailureKind),
    allowed_values("decision", SafetyDecision),
)

MEDIA_BLOB_MAX_BYTES = 2_097_152  # data-model `media_blobs`: 2 MB

media_blobs = Table(
    "media_blobs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_hash", Text, ForeignKey("users.user_hash", ondelete="CASCADE"), nullable=False),
    Column("purpose", Text, nullable=False),
    Column("mime_type", Text, nullable=False),
    Column("data", LargeBinary, nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(f"size_bytes <= {MEDIA_BLOB_MAX_BYTES}", name="size_cap"),
    CheckConstraint("size_bytes = octet_length(data)", name="size_matches"),
    allowed_values("purpose", MediaPurpose),
    Index(None, "expires_at"),
)

outbox_messages = Table(
    "outbox_messages",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column(
        "turn_id", UUID(as_uuid=True), ForeignKey("turns.id", ondelete="CASCADE"), nullable=False
    ),
    Column("part_no", SmallInteger, nullable=False),
    Column("user_hash", Text, ForeignKey("users.user_hash", ondelete="CASCADE"), nullable=False),
    Column("channel", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("text", Text, nullable=True),
    # An expired blob leaves the part without its media; the deliverer fails it (s06 §4.8)
    Column("audio_blob_id", UUID(as_uuid=True), ForeignKey("media_blobs.id", ondelete="SET NULL")),
    Column("image_blob_id", UUID(as_uuid=True), ForeignKey("media_blobs.id", ondelete="SET NULL")),
    Column("buttons", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("template", JSONB, nullable=True),
    Column("status", Text, nullable=False, server_default=OutboxStatus.PENDING.value),
    Column("attempts", SmallInteger, nullable=False, server_default=text("0")),
    Column("available_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("sending_since", DateTime(timezone=True), nullable=True),
    Column("provider_message_id", Text, nullable=True, unique=True),
    Column("last_error", Text, nullable=True),  # an error code, never user content
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("sent_at", DateTime(timezone=True), nullable=True),
    Column("delivered_at", DateTime(timezone=True), nullable=True),
    Column("read_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint("turn_id", "part_no"),
    Index(
        "ix_outbox_messages_unfinished_available_at",
        "status",
        "available_at",
        postgresql_where=text("status IN ('pending', 'sending')"),
    ),
    allowed_values("channel", Channel),
    allowed_values("kind", PartKind),
    allowed_values("status", OutboxStatus),
)

learner_activities = Table(
    "learner_activities",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "learner_id",
        UUID(as_uuid=True),
        ForeignKey("learners.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("activity_id", Text, nullable=False),  # catalogue slug
    Column("activity_version", Integer, nullable=False),  # catalogue version when offered
    Column(
        "offered_turn_id",
        UUID(as_uuid=True),
        ForeignKey("turns.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("status", Text, nullable=False),
    Column("child_response_summary", Text, nullable=True),  # ≤ 200 chars; cleared by retention
    # the khoj card made for this report, if any (C6); kept 7 days with its media_blobs row
    Column("card_blob_id", UUID(as_uuid=True), ForeignKey("media_blobs.id", ondelete="SET NULL")),
    # what SAM 3.1 counted in a photo of the child's work (C7): list[ObjectCount], never the photo
    Column("photo_findings", JSONB, nullable=True),
    Column("offered_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("reported_at", DateTime(timezone=True), nullable=True),
    CheckConstraint("char_length(child_response_summary) <= 200", name="summary_length"),
    allowed_values("status", ActivityStatus),
    Index("ix_learner_activities_learner_id_offered_at", "learner_id", text("offered_at DESC")),
)

child_sessions = Table(
    "child_sessions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "learner_id",
        UUID(as_uuid=True),
        ForeignKey("learners.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("user_hash", Text, ForeignKey("users.user_hash", ondelete="CASCADE"), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("ended_at", DateTime(timezone=True), nullable=True),  # NULL while open
    Column("turns_count", SmallInteger, nullable=False, server_default=text("0")),
    Column("end_reason", Text, nullable=True),
    # CuriosityDomain values the child asked about, for the parent's summary: never their words
    Column("topics", ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")),
    Column("summary_sent_at", DateTime(timezone=True), nullable=True),
    # The language the child asked for in this session (Language); NULL: they haven't asked
    Column("language", Text, nullable=True),
    allowed_values("end_reason", ChildSessionEndReason),
    allowed_values("language", Language),
    Index("ix_child_sessions_learner_id_started_at", "learner_id", text("started_at DESC")),
    Index(
        "uq_child_sessions_one_open_per_user",
        "user_hash",
        unique=True,
        postgresql_where=text("ended_at IS NULL"),
    ),
)

nudge_subscriptions = Table(
    "nudge_subscriptions",
    metadata,
    Column("user_hash", Text, ForeignKey("users.user_hash", ondelete="CASCADE"), primary_key=True),
    Column("enabled", Boolean, nullable=False),
    Column("local_time", Time, nullable=True),  # IST, as the parent chose
    Column("next_due_at", DateTime(timezone=True), nullable=True),  # NULL while off
    Column("last_sent_at", DateTime(timezone=True), nullable=True),
    Column("opted_in_at", DateTime(timezone=True), nullable=True),
    Column("opted_out_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(
        "NOT enabled OR (local_time IS NOT NULL AND next_due_at IS NOT NULL)",
        name="on_has_a_time",
    ),
    Index("ix_nudge_subscriptions_next_due_at", "next_due_at", postgresql_where=text("enabled")),
)

curiosity_signals = Table(
    "curiosity_signals",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column(
        "turn_id",
        UUID(as_uuid=True),
        ForeignKey("turns.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column(
        "learner_id",
        UUID(as_uuid=True),
        ForeignKey("learners.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("source", Text, nullable=False),  # parent_report, child_words, relayed_question
    Column("domains", ARRAY(Text), nullable=False),  # CuriosityDomain values, at most 3
    Column("engagement", SmallInteger, nullable=False),
    Column("child_asked_question", Boolean, nullable=False),
    Column("prompt_version", Text, nullable=False),
    Column("extracted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("engagement BETWEEN 0 AND 3", name="engagement_range"),
    CheckConstraint("cardinality(domains) <= 3", name="at_most_three_domains"),
    CheckConstraint(
        "source IN ('parent_report', 'child_words', 'relayed_question')", name="source_valid"
    ),
    Index(None, "learner_id"),
)

rate_limit_counters = Table(
    "rate_limit_counters",
    metadata,
    Column("key", Text, primary_key=True),  # e.g. demo:session:<user hash>; never a raw IP
    Column("window_start", DateTime(timezone=True), primary_key=True),
    Column("count", Integer, nullable=False),
    Index(None, "window_start"),
)

corpus_documents = Table(
    "corpus_documents",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("path", Text, nullable=False, unique=True),  # repo-relative: corpus/<topic>/<slug>.md
    Column("title", Text, nullable=False),
    Column("source_url", Text, nullable=False),
    Column("retrieved_on", Date, nullable=False),
    Column("topic", Text, nullable=False),
    Column("language", Text, nullable=False, server_default=text("'english'")),
    Column("grades", ARRAY(SmallInteger), nullable=False, server_default=text("'{}'")),
    Column("keywords", ARRAY(Text), nullable=False),  # stored upper-cased
    Column("content_sha256", Text, nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    allowed_values("topic", CorpusTopic),
)

corpus_chunks = Table(
    "corpus_chunks",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "document_id",
        UUID(as_uuid=True),
        ForeignKey("corpus_documents.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("position", SmallInteger, nullable=False),
    Column("heading_path", Text, nullable=False),
    Column("text", Text, nullable=False),
    # Keyword retrieval only (s11, 2026-10-29): English stemming over the heading and the text.
    Column(
        "tsv",
        TSVECTOR,
        Computed("to_tsvector('english', heading_path || ' ' || text)", persisted=True),
    ),
    UniqueConstraint("document_id", "position"),
    Index("ix_corpus_chunks_tsv", "tsv", postgresql_using="gin"),
)

profile_memory = Table(
    "profile_memory",
    metadata,
    Column("user_hash", Text, ForeignKey("users.user_hash", ondelete="CASCADE"), primary_key=True),
    Column("summary", Text, nullable=False),
    Column("ambitions", ARRAY(Text), nullable=False),
    Column("constraints", ARRAY(Text), nullable=False),
    Column("source_turn_id", UUID(as_uuid=True), nullable=True),
    Column("prompt_version", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("char_length(summary) <= 600", name="summary_length"),
    CheckConstraint(
        "cardinality(ambitions) <= 5 AND cardinality(constraints) <= 5", name="at_most_five"
    ),
)

roadmaps = Table(
    "roadmaps",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_hash", Text, ForeignKey("users.user_hash", ondelete="CASCADE"), nullable=False),
    Column("goal", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    allowed_values("status", RoadmapStatus),
    Index(
        "ux_roadmaps_one_active_per_user",
        "user_hash",
        unique=True,
        postgresql_where=text("status = 'active'"),
    ),
)

roadmap_steps = Table(
    "roadmap_steps",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "roadmap_id",
        UUID(as_uuid=True),
        ForeignKey("roadmaps.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("position", SmallInteger, nullable=False),
    Column("action", Text, nullable=False),
    Column("timeframe", Text, nullable=False),
    Column("cost_inr", Numeric(12, 2), nullable=True),
    Column("source_url", Text, nullable=True),
    Column("status", Text, nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint("roadmap_id", "position"),
    allowed_values("status", RoadmapStepStatus),
)

aspiration_signals = Table(
    "aspiration_signals",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column(
        "turn_id",
        UUID(as_uuid=True),
        ForeignKey("turns.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column(
        "learner_id",
        UUID(as_uuid=True),
        ForeignKey("learners.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("fields", ARRAY(Text), nullable=False),  # AspirationField values, at most 3
    Column("specificity", SmallInteger, nullable=False),
    Column("constraints", ARRAY(Text), nullable=False),  # ConstraintKind values, at most 3
    Column("sentiment", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),
    Column("extracted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("specificity BETWEEN 0 AND 4", name="specificity_range"),
    CheckConstraint(
        "cardinality(fields) <= 3 AND cardinality(constraints) <= 3", name="at_most_three"
    ),
    allowed_values("sentiment", Sentiment),
    Index(None, "learner_id"),
)
