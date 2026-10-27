"""Table definitions (data-model.md). Each table is created by its step's Alembic migration.

Enum columns are text with a CHECK listing the StrEnum values, so Python and the database agree.
"""

from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.domain.enums import (
    Channel,
    ConversationState,
    FailureKind,
    FixedReplyKind,
    InboxStatus,
    Language,
    MessageKind,
    OutboxStatus,
    PartKind,
    Route,
    SafetyDecision,
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
    Column("last_inbound_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("user_hash ~ '^[0-9a-f]{64}$'", name="user_hash_is_hex64"),
    allowed_values("channel", Channel),
    allowed_values("state", ConversationState),
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
    # media_blobs arrives with S6, which adds the foreign keys on these two
    Column("audio_blob_id", UUID(as_uuid=True), nullable=True),
    Column("image_blob_id", UUID(as_uuid=True), nullable=True),
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
