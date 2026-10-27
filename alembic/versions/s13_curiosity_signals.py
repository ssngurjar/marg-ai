"""s13: curiosity_signals, what a child engaged with on each journey turn (data-model.md).

Revision ID: s13_curiosity_signals
Revises: s10b_nudges
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "s13_curiosity_signals"
down_revision: str | Sequence[str] | None = "s10b_nudges"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "curiosity_signals",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("turn_id", sa.UUID(), nullable=False),
        sa.Column("learner_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("domains", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("engagement", sa.SmallInteger(), nullable=False),
        sa.Column("child_asked_question", sa.Boolean(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column(
            "extracted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "engagement BETWEEN 0 AND 3", name="ck_curiosity_signals_engagement_range"
        ),
        sa.CheckConstraint(
            "cardinality(domains) <= 3", name="ck_curiosity_signals_at_most_three_domains"
        ),
        sa.CheckConstraint(
            "source IN ('parent_report', 'child_words', 'relayed_question')",
            name="ck_curiosity_signals_source_valid",
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["turns.id"], name="fk_curiosity_signals_turn_id_turns", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name="fk_curiosity_signals_learner_id_learners",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_curiosity_signals"),
        sa.UniqueConstraint("turn_id", name="uq_curiosity_signals_turn_id"),
    )
    op.create_index("ix_curiosity_signals_learner_id", "curiosity_signals", ["learner_id"])


def downgrade() -> None:
    op.drop_index("ix_curiosity_signals_learner_id", table_name="curiosity_signals")
    op.drop_table("curiosity_signals")
