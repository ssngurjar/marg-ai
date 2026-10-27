"""s14: the web demo's rate limits, and web voice notes on inbox messages (data-model.md).

Revision ID: s14_web_demo
Revises: s10b_khoj_cards
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "s14_web_demo"
down_revision: str | Sequence[str] | None = "s10b_khoj_cards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("inbox_messages", sa.Column("media_blob_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_inbox_messages_media_blob_id_media_blobs",
        "inbox_messages",
        "media_blobs",
        ["media_blob_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "rate_limit_counters",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key", "window_start", name="pk_rate_limit_counters"),
    )
    op.create_index("ix_rate_limit_counters_window_start", "rate_limit_counters", ["window_start"])


def downgrade() -> None:
    op.drop_index("ix_rate_limit_counters_window_start", table_name="rate_limit_counters")
    op.drop_table("rate_limit_counters")
    op.drop_constraint(
        "fk_inbox_messages_media_blob_id_media_blobs", "inbox_messages", type_="foreignkey"
    )
    op.drop_column("inbox_messages", "media_blob_id")
