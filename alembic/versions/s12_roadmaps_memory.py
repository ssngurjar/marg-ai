"""s12: students' roadmaps and profile memory (s12 §6; data-model).

At most one active roadmap per user (a partial unique index), so two racing saves can't leave
two. Everything cascades when the user is deleted.

Revision ID: s12_roadmaps_memory
Revises: s11_corpus_tables
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "s12_roadmaps_memory"
down_revision: str | Sequence[str] | None = "s11_corpus_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "profile_memory",
        sa.Column("user_hash", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("ambitions", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("constraints", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("source_turn_id", sa.UUID(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("char_length(summary) <= 600", name="summary_length"),
        sa.CheckConstraint(
            "cardinality(ambitions) <= 5 AND cardinality(constraints) <= 5", name="at_most_five"
        ),
        sa.ForeignKeyConstraint(["user_hash"], ["users.user_hash"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_hash"),
    )
    op.create_table(
        "roadmaps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_hash", sa.Text(), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('active', 'completed', 'abandoned')", name="status_valid"),
        sa.ForeignKeyConstraint(["user_hash"], ["users.user_hash"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_roadmaps_one_active_per_user",
        "roadmaps",
        ["user_hash"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "roadmap_steps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("roadmap_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("timeframe", sa.Text(), nullable=False),
        sa.Column("cost_inr", sa.Numeric(12, 2), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('todo', 'done', 'skipped')", name="status_valid"),
        sa.ForeignKeyConstraint(["roadmap_id"], ["roadmaps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("roadmap_id", "position"),
    )


def downgrade() -> None:
    op.drop_table("roadmap_steps")
    op.drop_index("ux_roadmaps_one_active_per_user", table_name="roadmaps")
    op.drop_table("roadmaps")
    op.drop_table("profile_memory")
