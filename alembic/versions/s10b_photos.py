"""s10b: activity photos (C7): learner_activities.photo_findings and the inbound_photo purpose.

A photo is never stored beyond its turn. WhatsApp photos are fetched from Meta and kept in memory;
a web visitor's photo waits in media_blobs (purpose inbound_photo) only until its turn has looked
at it, and is deleted in that turn's finalize (owner, 2026-10-28).

Revision ID: s10b_photos
Revises: s14_web_demo
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "s10b_photos"
down_revision: str | Sequence[str] | None = "s14_web_demo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PURPOSES_BEFORE = "'inbound_audio', 'reply_audio', 'khoj_card'"
PURPOSES_AFTER = "'inbound_audio', 'inbound_photo', 'reply_audio', 'khoj_card'"
# The naming convention doubled the prefix when s06 created it; op.f() names it exactly.
EXISTING_CHECK = "ck_media_blobs_ck_media_blobs_purpose_valid"


def upgrade() -> None:
    op.add_column("learner_activities", sa.Column("photo_findings", JSONB(), nullable=True))
    op.drop_constraint(op.f(EXISTING_CHECK), "media_blobs", type_="check")
    op.create_check_constraint(
        op.f(EXISTING_CHECK), "media_blobs", f"purpose IN ({PURPOSES_AFTER})"
    )


def downgrade() -> None:
    op.execute("DELETE FROM media_blobs WHERE purpose = 'inbound_photo'")
    op.drop_constraint(op.f(EXISTING_CHECK), "media_blobs", type_="check")
    op.create_check_constraint(
        op.f(EXISTING_CHECK), "media_blobs", f"purpose IN ({PURPOSES_BEFORE})"
    )
    op.drop_column("learner_activities", "photo_findings")
