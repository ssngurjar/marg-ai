"""s13: aspiration_signals, one row per student mentor or roadmap turn (s13 §4.3; data-model).

Revision ID: s13_aspiration_signals
Revises: s12_roadmaps_memory
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "s13_aspiration_signals"
down_revision: str | Sequence[str] | None = "s12_roadmaps_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "aspiration_signals",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("turn_id", sa.UUID(), nullable=False),
        sa.Column("learner_id", sa.UUID(), nullable=False),
        sa.Column("fields", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("specificity", sa.SmallInteger(), nullable=False),
        sa.Column("constraints", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("sentiment", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column(
            "extracted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("specificity BETWEEN 0 AND 4", name="specificity_range"),
        sa.CheckConstraint(
            "cardinality(fields) <= 3 AND cardinality(constraints) <= 3", name="at_most_three"
        ),
        sa.CheckConstraint(
            "sentiment IN ('positive', 'neutral', 'negative')", name="sentiment_valid"
        ),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["turn_id"], ["turns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("turn_id"),
    )
    op.create_index(op.f("ix_aspiration_signals_learner_id"), "aspiration_signals", ["learner_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_aspiration_signals_learner_id"), table_name="aspiration_signals")
    op.drop_table("aspiration_signals")
