"""s06: media_blobs, reply audio kept for 24 h until the sender uploads it (data-model.md).

Also gives outbox_messages.audio_blob_id and image_blob_id their foreign keys, which waited for
this table (s04 decisions log).

Revision ID: s06_media_blobs
Revises: s10b_journey
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "s06_media_blobs"
down_revision: str | Sequence[str] | None = "s10b_journey"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PURPOSES = "'inbound_audio', 'reply_audio', 'khoj_card'"


def upgrade() -> None:
    op.create_table(
        "media_blobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_hash", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("size_bytes <= 2097152", name="ck_media_blobs_size_cap"),
        sa.CheckConstraint("size_bytes = octet_length(data)", name="ck_media_blobs_size_matches"),
        sa.CheckConstraint(f"purpose IN ({PURPOSES})", name="ck_media_blobs_purpose_valid"),
        sa.ForeignKeyConstraint(
            ["user_hash"],
            ["users.user_hash"],
            name="fk_media_blobs_user_hash_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_media_blobs"),
    )
    op.create_index("ix_media_blobs_expires_at", "media_blobs", ["expires_at"])
    for column in ("audio_blob_id", "image_blob_id"):
        op.create_foreign_key(
            f"fk_outbox_messages_{column}_media_blobs",
            "outbox_messages",
            "media_blobs",
            [column],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for column in ("audio_blob_id", "image_blob_id"):
        op.drop_constraint(
            f"fk_outbox_messages_{column}_media_blobs", "outbox_messages", type_="foreignkey"
        )
    op.drop_index("ix_media_blobs_expires_at", table_name="media_blobs")
    op.drop_table("media_blobs")
