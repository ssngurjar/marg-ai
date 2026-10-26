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
    LargeBinary,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.domain.enums import Channel, ConversationState, InboxStatus, MessageKind

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
    Column("provider_sent_at", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("channel", "external_id"),
    Index(None, "user_hash", "status"),
    allowed_values("channel", Channel),
    allowed_values("kind", MessageKind),
    allowed_values("status", InboxStatus),
)
