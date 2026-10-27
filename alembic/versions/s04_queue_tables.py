"""s04: turns, turn_steps, outbox_messages, and the inbox's retry columns (data-model.md).

Exception E1 (one process): the users lease columns are Phase 2 and aren't added. media_blobs
arrives with S6, which adds the foreign keys on outbox_messages.audio_blob_id / image_blob_id.

Revision ID: s04_queue_tables
Revises: s03_users_inbox
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "s04_queue_tables"
down_revision: str | Sequence[str] | None = "s03_users_inbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FAILURE_KINDS = (
    "'timeout', 'rate_limited', 'unavailable', 'invalid_response', 'empty_input', "
    "'unsupported_input', 'budget_exceeded', 'internal'"
)
STEP_NAMES = (
    "'fetch_media', 'transcribe', 'safety_in', 'route', 'generate', 'translate', 'safety_out', "
    "'synthesize', 'enqueue_reply', 'extract_signals', 'update_memory', 'fetch_image', "
    "'analyze_image', 'make_card'"
)
FIXED_REPLY_KINDS = (
    "'crisis', 'holding', 'repeat_please', 'try_again_later', 'too_long', 'unsupported_media', "
    "'refuse', 'onboarding', 'consent_declined', 'data_deleted', 'ask_chapter', 'nudge', "
    "'photo_has_person', 'photo_not_needed', 'child_talk_not_enabled', 'child_talk_cooldown', "
    "'child_session_end'"
)
LANGUAGES = "'hindi', 'hinglish', 'english'"
ROUTES = (
    "'onboarding', 'exposure', 'mentor', 'roadmap', 'journey', 'crisis', 'refuse', 'off_topic', "
    "'data_deletion', 'repeat_please', 'dashboard_link', 'nudge', 'khoj_card', 'child_talk'"
)
TURN_STATUSES = "'processing', 'completed', 'failed'"
CHANNELS = "'whatsapp', 'web'"
PART_KINDS = "'text', 'audio', 'image', 'interactive', 'template'"
OUTBOX_STATUSES = "'pending', 'sending', 'sent', 'delivered', 'read', 'failed'"
SAFETY_DECISIONS = "'allow', 'block', 'crisis'"
STEP_OUTCOMES = "'ok', 'degraded', 'failed', 'skipped'"


def upgrade() -> None:
    op.create_table(
        "turns",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("route", sa.Text(), nullable=True),
        sa.Column("user_text", sa.Text(), nullable=True),
        sa.Column("reply_text", sa.Text(), nullable=True),
        sa.Column("reply_register", sa.Text(), nullable=True),
        sa.Column("fixed_reply_kind", sa.Text(), nullable=True),
        sa.Column(
            "prompt_versions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("failure_step", sa.Text(), nullable=True),
        sa.Column("failure_kind", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"failure_kind IN ({FAILURE_KINDS})",
            name=op.f("ck_turns_failure_kind_valid"),
        ),
        sa.CheckConstraint(
            f"failure_step IN ({STEP_NAMES})",
            name=op.f("ck_turns_failure_step_valid"),
        ),
        sa.CheckConstraint(
            f"fixed_reply_kind IN ({FIXED_REPLY_KINDS})",
            name=op.f("ck_turns_fixed_reply_kind_valid"),
        ),
        sa.CheckConstraint(
            f"reply_register IN ({LANGUAGES})",
            name=op.f("ck_turns_reply_register_valid"),
        ),
        sa.CheckConstraint(
            f"route IN ({ROUTES})",
            name=op.f("ck_turns_route_valid"),
        ),
        sa.CheckConstraint(f"status IN ({TURN_STATUSES})", name=op.f("ck_turns_status_valid")),
        sa.ForeignKeyConstraint(
            ["user_hash"],
            ["users.user_hash"],
            name=op.f("fk_turns_user_hash_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_turns")),
    )
    op.create_index(op.f("ix_turns_started_at"), "turns", ["started_at"], unique=False)
    op.create_index(
        "ix_turns_user_hash_started_at",
        "turns",
        ["user_hash", sa.literal_column("started_at DESC")],
        unique=False,
    )
    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("turn_id", sa.UUID(), nullable=False),
        sa.Column("part_no", sa.SmallInteger(), nullable=False),
        sa.Column("user_hash", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("audio_blob_id", sa.UUID(), nullable=True),
        sa.Column("image_blob_id", sa.UUID(), nullable=True),
        sa.Column(
            "buttons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("template", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sending_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"channel IN ({CHANNELS})", name=op.f("ck_outbox_messages_channel_valid")
        ),
        sa.CheckConstraint(
            f"kind IN ({PART_KINDS})",
            name=op.f("ck_outbox_messages_kind_valid"),
        ),
        sa.CheckConstraint(
            f"status IN ({OUTBOX_STATUSES})",
            name=op.f("ck_outbox_messages_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"],
            ["turns.id"],
            name=op.f("fk_outbox_messages_turn_id_turns"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_hash"],
            ["users.user_hash"],
            name=op.f("fk_outbox_messages_user_hash_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_messages")),
        sa.UniqueConstraint(
            "provider_message_id", name=op.f("uq_outbox_messages_provider_message_id")
        ),
        sa.UniqueConstraint("turn_id", "part_no", name=op.f("uq_outbox_messages_turn_id_part_no")),
    )
    op.create_index(
        "ix_outbox_messages_unfinished_available_at",
        "outbox_messages",
        ["status", "available_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending', 'sending')"),
    )
    op.create_table(
        "turn_steps",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("turn_id", sa.UUID(), nullable=False),
        sa.Column("step", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("failure_kind", sa.Text(), nullable=True),
        sa.Column("decision", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("audio_seconds", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column(
            "cost_usd",
            sa.Numeric(precision=12, scale=6),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            f"decision IN ({SAFETY_DECISIONS})", name=op.f("ck_turn_steps_decision_valid")
        ),
        sa.CheckConstraint(
            f"failure_kind IN ({FAILURE_KINDS})",
            name=op.f("ck_turn_steps_failure_kind_valid"),
        ),
        sa.CheckConstraint(
            f"outcome IN ({STEP_OUTCOMES})",
            name=op.f("ck_turn_steps_outcome_valid"),
        ),
        sa.CheckConstraint(
            f"step IN ({STEP_NAMES})",
            name=op.f("ck_turn_steps_step_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["turns.id"], name=op.f("fk_turn_steps_turn_id_turns"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_turn_steps")),
    )
    op.create_index(op.f("ix_turn_steps_started_at"), "turn_steps", ["started_at"], unique=False)
    op.create_index(op.f("ix_turn_steps_turn_id"), "turn_steps", ["turn_id"], unique=False)
    op.add_column(
        "inbox_messages",
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "inbox_messages",
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column("inbox_messages", sa.Column("turn_id", sa.UUID(), nullable=True))
    op.create_index(
        "ix_inbox_messages_pending_available_at",
        "inbox_messages",
        ["status", "available_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_foreign_key(
        op.f("fk_inbox_messages_turn_id_turns"),
        "inbox_messages",
        "turns",
        ["turn_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_inbox_messages_turn_id_turns"), "inbox_messages", type_="foreignkey"
    )
    op.drop_index(
        "ix_inbox_messages_pending_available_at",
        table_name="inbox_messages",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_column("inbox_messages", "turn_id")
    op.drop_column("inbox_messages", "available_at")
    op.drop_column("inbox_messages", "attempts")
    op.drop_index(op.f("ix_turn_steps_turn_id"), table_name="turn_steps")
    op.drop_index(op.f("ix_turn_steps_started_at"), table_name="turn_steps")
    op.drop_table("turn_steps")
    op.drop_index(
        "ix_outbox_messages_unfinished_available_at",
        table_name="outbox_messages",
        postgresql_where=sa.text("status IN ('pending', 'sending')"),
    )
    op.drop_table("outbox_messages")
    op.drop_index("ix_turns_user_hash_started_at", table_name="turns")
    op.drop_index(op.f("ix_turns_started_at"), table_name="turns")
    op.drop_table("turns")
