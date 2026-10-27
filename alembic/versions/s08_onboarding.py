"""s08: onboarding columns on users, consent_events, learners (data-model.md).

Every foreign key to users cascades, so deleting the user row (delete-my-data) removes their
consent events and learners too.

Revision ID: s08_onboarding
Revises: s04_queue_tables
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "s08_onboarding"
down_revision: str | Sequence[str] | None = "s04_queue_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = "'student', 'teacher', 'parent'"
LANGUAGES = "'hindi', 'hinglish', 'english'"
CONSENT_EVENT_KINDS = (
    "'granted', 'guardian_confirmed', 'child_profile_consent', 'child_talk_consent', "
    "'revoked', 'deletion_requested'"
)
LEARNER_RELATIONS = "'self', 'parent'"


def upgrade() -> None:
    op.add_column("users", sa.Column("role", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("grade", sa.SmallInteger(), nullable=True))
    op.add_column("users", sa.Column("subject", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("district", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("language", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "guardian_confirmed", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.add_column("users", sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("pending_question", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("purge_after_turn_id", sa.UUID(), nullable=True))
    op.create_check_constraint("ck_users_grade_range", "users", "grade BETWEEN 1 AND 12")
    op.create_check_constraint("ck_users_role_valid", "users", f"role IN ({ROLES})")
    op.create_check_constraint("ck_users_language_valid", "users", f"language IN ({LANGUAGES})")
    op.create_index(
        "ix_users_purge_after_turn_id",
        "users",
        ["purge_after_turn_id"],
        postgresql_where=sa.text("purge_after_turn_id IS NOT NULL"),
    )

    op.create_table(
        "consent_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_hash", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"kind IN ({CONSENT_EVENT_KINDS})", name="ck_consent_events_kind_valid"),
        sa.ForeignKeyConstraint(
            ["user_hash"],
            ["users.user_hash"],
            name="fk_consent_events_user_hash_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_consent_events"),
    )
    op.create_index("ix_consent_events_user_hash", "consent_events", ["user_hash"])

    op.create_table(
        "learners",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_user_hash", sa.Text(), nullable=False),
        sa.Column("relation", sa.Text(), nullable=False),
        sa.Column("nickname", sa.Text(), nullable=True),
        sa.Column("birth_year", sa.SmallInteger(), nullable=False),
        sa.Column("child_talk_consented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "birth_year BETWEEN 2000 AND 2100", name="ck_learners_birth_year_sanity"
        ),
        sa.CheckConstraint("char_length(nickname) <= 20", name="ck_learners_nickname_length"),
        sa.CheckConstraint(f"relation IN ({LEARNER_RELATIONS})", name="ck_learners_relation_valid"),
        sa.ForeignKeyConstraint(
            ["owner_user_hash"],
            ["users.user_hash"],
            name="fk_learners_owner_user_hash_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_learners"),
    )
    op.create_index("ix_learners_owner_user_hash", "learners", ["owner_user_hash"])
    op.create_index(
        "uq_learners_one_self_per_owner",
        "learners",
        ["owner_user_hash"],
        unique=True,
        postgresql_where=sa.text("relation = 'self'"),
    )


def downgrade() -> None:
    op.drop_index("uq_learners_one_self_per_owner", table_name="learners")
    op.drop_index("ix_learners_owner_user_hash", table_name="learners")
    op.drop_table("learners")
    op.drop_index("ix_consent_events_user_hash", table_name="consent_events")
    op.drop_table("consent_events")
    op.drop_index("ix_users_purge_after_turn_id", table_name="users")
    op.drop_constraint("ck_users_language_valid", "users", type_="check")
    op.drop_constraint("ck_users_role_valid", "users", type_="check")
    op.drop_constraint("ck_users_grade_range", "users", type_="check")
    for column in (
        "purge_after_turn_id",
        "pending_question",
        "consented_at",
        "guardian_confirmed",
        "language",
        "district",
        "subject",
        "grade",
        "role",
    ):
        op.drop_column("users", column)
