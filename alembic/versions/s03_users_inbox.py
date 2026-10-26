"""s03: users and inbox_messages (data-model.md).

Revision ID: s03_users_inbox
Revises:
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "s03_users_inbox"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.func.now()
CHANNELS = "'whatsapp', 'web'"
CONVERSATION_STATES = (
    "'new', 'awaiting_consent', 'awaiting_role', 'awaiting_guardian', 'awaiting_child', "
    "'awaiting_profile', 'active', 'awaiting_deletion_confirm'"
)
MESSAGE_KINDS = "'text', 'audio', 'image', 'interactive', 'unsupported'"
INBOX_STATUSES = "'pending', 'processing', 'done', 'failed'"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_hash", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("address_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("state", sa.Text(), server_default="new", nullable=False),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("user_hash", name="pk_users"),
        sa.CheckConstraint("user_hash ~ '^[0-9a-f]{64}$'", name="ck_users_user_hash_is_hex64"),
        sa.CheckConstraint(f"channel IN ({CHANNELS})", name="ck_users_channel_valid"),
        sa.CheckConstraint(f"state IN ({CONVERSATION_STATES})", name="ck_users_state_valid"),
    )
    op.create_table(
        "inbox_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("user_hash", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("media_provider_id", sa.Text(), nullable=True),
        sa.Column("media_mime_type", sa.Text(), nullable=True),
        sa.Column("interactive_reply_id", sa.Text(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("provider_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_inbox_messages"),
        sa.ForeignKeyConstraint(
            ["user_hash"], ["users.user_hash"],
            name="fk_inbox_messages_user_hash_users", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("channel", "external_id", name="uq_inbox_messages_channel_external_id"),
        sa.CheckConstraint(f"channel IN ({CHANNELS})", name="ck_inbox_messages_channel_valid"),
        sa.CheckConstraint(f"kind IN ({MESSAGE_KINDS})", name="ck_inbox_messages_kind_valid"),
        sa.CheckConstraint(f"status IN ({INBOX_STATUSES})", name="ck_inbox_messages_status_valid"),
    )  # fmt: skip
    op.create_index("ix_inbox_messages_user_hash_status", "inbox_messages", ["user_hash", "status"])


def downgrade() -> None:
    op.drop_index("ix_inbox_messages_user_hash_status", table_name="inbox_messages")
    op.drop_table("inbox_messages")
    op.drop_table("users")
