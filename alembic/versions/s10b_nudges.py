"""s10b: nudge_subscriptions, the daily khoj message a parent opted into (data-model.md).

Revision ID: s10b_nudges
Revises: s10b_child_sessions
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "s10b_nudges"
down_revision: str | Sequence[str] | None = "s10b_child_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "nudge_subscriptions",
        sa.Column("user_hash", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("local_time", sa.Time(), nullable=True),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opted_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opted_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "NOT enabled OR (local_time IS NOT NULL AND next_due_at IS NOT NULL)",
            name="ck_nudge_subscriptions_on_has_a_time",
        ),
        sa.ForeignKeyConstraint(
            ["user_hash"],
            ["users.user_hash"],
            name="fk_nudge_subscriptions_user_hash_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_hash", name="pk_nudge_subscriptions"),
    )
    op.create_index(
        "ix_nudge_subscriptions_next_due_at",
        "nudge_subscriptions",
        ["next_due_at"],
        postgresql_where=sa.text("enabled"),
    )


def downgrade() -> None:
    op.drop_index("ix_nudge_subscriptions_next_due_at", table_name="nudge_subscriptions")
    op.drop_table("nudge_subscriptions")
