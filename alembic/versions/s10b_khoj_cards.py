"""s10b: learner_activities.card_blob_id, the khoj card made for a report (C6, data-model.md).

Revision ID: s10b_khoj_cards
Revises: s13_curiosity_signals
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "s10b_khoj_cards"
down_revision: str | Sequence[str] | None = "s13_curiosity_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("learner_activities", sa.Column("card_blob_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_learner_activities_card_blob_id_media_blobs",
        "learner_activities",
        "media_blobs",
        ["card_blob_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_learner_activities_card_blob_id_media_blobs", "learner_activities", type_="foreignkey"
    )
    op.drop_column("learner_activities", "card_blob_id")
