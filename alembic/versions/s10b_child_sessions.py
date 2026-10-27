"""s10b: child_sessions, a child talking to Marg.ai directly (C13, data-model.md).

At most one open session per user: the parent's phone holds one child's conversation at a time.

Revision ID: s10b_child_sessions
Revises: s06_media_blobs
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "s10b_child_sessions"
down_revision: str | Sequence[str] | None = "s06_media_blobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

END_REASONS = "'turn_limit', 'time_limit', 'child_ended', 'crisis', 'expired'"


def upgrade() -> None:
    op.create_table(
        "child_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("learner_id", sa.UUID(), nullable=False),
        sa.Column("user_hash", sa.Text(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("turns_count", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("end_reason", sa.Text(), nullable=True),
        sa.Column(
            "topics",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("summary_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"end_reason IN ({END_REASONS})", name="ck_child_sessions_end_reason_valid"
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name="fk_child_sessions_learner_id_learners",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_hash"],
            ["users.user_hash"],
            name="fk_child_sessions_user_hash_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_child_sessions"),
    )
    op.create_index(
        "ix_child_sessions_learner_id_started_at",
        "child_sessions",
        ["learner_id", sa.text("started_at DESC")],
    )
    op.create_index(
        "uq_child_sessions_one_open_per_user",
        "child_sessions",
        ["user_hash"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_child_sessions_one_open_per_user", table_name="child_sessions")
    op.drop_index("ix_child_sessions_learner_id_started_at", table_name="child_sessions")
    op.drop_table("child_sessions")
