"""s10b (2026-10-29): a child session remembers the language the child asked for.

A child who says "Hindi" in their session gets Hindi for the rest of it; the parent's account
language doesn't change (C16 still holds). NULL: the child hasn't asked, so each reply follows
how the child writes, else the family's language.

Revision ID: s10b_child_session_language
Revises: s11_keyword_retrieval
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "s10b_child_session_language"
down_revision: str | Sequence[str] | None = "s11_keyword_retrieval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("child_sessions", sa.Column("language", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_child_sessions_language_valid",
        "child_sessions",
        "language IN ('hindi', 'hinglish', 'english')",  # NULL passes a check
    )


def downgrade() -> None:
    op.drop_constraint("ck_child_sessions_language_valid", "child_sessions", type_="check")
    op.drop_column("child_sessions", "language")
