"""s10b: a daily limit on each child's own talk, picked by the parent (s10b §4.16).

The session limits keep one conversation short, but after each cooldown a child could start
another, all day. Owner, 2026-11-13:

- `learners.child_talk_daily_limit`: the parent's pick for that child (`DailyTalkLimit`: 20, 30
  or 60 minutes a day across all their sessions, or no limit). NULL: not picked yet, so
  ChildDailyLimitRules.DEFAULT (30 minutes) applies; every child consented before this
  migration starts there.
- `child_sessions.last_answered_at`: when the child's last question in the session was
  answered. A session the child left without a goodbye counts until then, not until
  maintenance closed it. Sessions from before this migration have none and count nothing.
- `child_sessions.end_reason` may be `daily_limit`: the child's time for the day ran out.

Revision ID: s10b_child_talk_daily_limit
Revises: s08_graduate_level
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "s10b_child_talk_daily_limit"
down_revision: str | Sequence[str] | None = "s08_graduate_level"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DAILY_LIMITS = "'20_minutes', '30_minutes', '60_minutes', 'no_limit'"
END_REASONS_BEFORE = "'turn_limit', 'time_limit', 'child_ended', 'crisis', 'expired'"
END_REASONS = f"{END_REASONS_BEFORE}, 'daily_limit'"


def upgrade() -> None:
    op.add_column("learners", sa.Column("child_talk_daily_limit", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_learners_child_talk_daily_limit_valid",
        "learners",
        f"child_talk_daily_limit IN ({DAILY_LIMITS})",  # NULL passes a check
    )
    op.add_column(
        "child_sessions",
        sa.Column("last_answered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint("ck_child_sessions_end_reason_valid", "child_sessions", type_="check")
    op.create_check_constraint(
        "ck_child_sessions_end_reason_valid", "child_sessions", f"end_reason IN ({END_REASONS})"
    )


def downgrade() -> None:
    # A session that ended on the daily limit ended on a limit, as a turn-limit one does.
    op.execute(
        "UPDATE child_sessions SET end_reason = 'turn_limit' WHERE end_reason = 'daily_limit'"
    )
    op.drop_constraint("ck_child_sessions_end_reason_valid", "child_sessions", type_="check")
    op.create_check_constraint(
        "ck_child_sessions_end_reason_valid",
        "child_sessions",
        f"end_reason IN ({END_REASONS_BEFORE})",
    )
    op.drop_column("child_sessions", "last_answered_at")
    op.drop_constraint("ck_learners_child_talk_daily_limit_valid", "learners", type_="check")
    op.drop_column("learners", "child_talk_daily_limit")
