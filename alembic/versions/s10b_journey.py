"""s10b: learner_activities, the khoj offered to each child and how it went (data-model.md).

Photo findings and the khoj card column arrive with those features (and S6's media_blobs).

Revision ID: s10b_journey
Revises: s08_onboarding
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "s10b_journey"
down_revision: str | Sequence[str] | None = "s08_onboarding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVITY_STATUSES = "'offered', 'done', 'skipped'"


def upgrade() -> None:
    op.create_table(
        "learner_activities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("learner_id", sa.UUID(), nullable=False),
        sa.Column("activity_id", sa.Text(), nullable=False),
        sa.Column("activity_version", sa.Integer(), nullable=False),
        sa.Column("offered_turn_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("child_response_summary", sa.Text(), nullable=True),
        sa.Column(
            "offered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "char_length(child_response_summary) <= 200",
            name="ck_learner_activities_summary_length",
        ),
        sa.CheckConstraint(
            f"status IN ({ACTIVITY_STATUSES})", name="ck_learner_activities_status_valid"
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name="fk_learner_activities_learner_id_learners",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["offered_turn_id"],
            ["turns.id"],
            name="fk_learner_activities_offered_turn_id_turns",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_learner_activities"),
    )
    op.create_index(
        "ix_learner_activities_learner_id_offered_at",
        "learner_activities",
        ["learner_id", sa.text("offered_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_learner_activities_learner_id_offered_at", table_name="learner_activities")
    op.drop_table("learner_activities")
