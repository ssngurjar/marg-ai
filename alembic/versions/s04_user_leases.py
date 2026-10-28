"""s04 (E1 upgrade): per-user turn leases, so several workers share one database (s04 §4.3, §4.8).

Revision ID: s04_user_leases
Revises: s13_aspiration_signals
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "s04_user_leases"
down_revision: str | Sequence[str] | None = "s13_aspiration_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("lease_owner", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        op.f("ix_users_lease_expires_at"),
        "users",
        ["lease_expires_at"],
        postgresql_where=sa.text("lease_owner IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_users_lease_expires_at"), table_name="users")
    op.drop_column("users", "lease_expires_at")
    op.drop_column("users", "lease_owner")
