"""s13: the turn_metrics view, one definition of a turn's latency, cost and success (s13 §4.1).

User latency runs from the first inbound message being stored to the first reply part being
sent; nudge turns have no inbound message, so theirs is NULL. `served_ok`: the turn completed and
the user got a real answer, not the HOLDING or TRY_AGAIN_LATER fallback.

Revision ID: s13_turn_metrics
Revises: s10b_photos
Create Date: 2026-10-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "s13_turn_metrics"
down_revision: str | Sequence[str] | None = "s10b_photos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIEW turn_metrics AS
        SELECT t.id AS turn_id,
               t.user_hash,
               t.route,
               t.status,
               t.fixed_reply_kind,
               t.failure_step,
               t.failure_kind,
               t.started_at,
               first_in.received_at AS first_received_at,
               first_out.sent_at AS first_sent_at,
               EXTRACT(EPOCH FROM (first_out.sent_at - first_in.received_at)) * 1000
                   AS user_latency_ms,
               COALESCE(steps.cost_usd, 0) AS cost_usd,
               (t.status = 'completed'
                AND (t.fixed_reply_kind IS NULL
                     OR t.fixed_reply_kind NOT IN ('holding', 'try_again_later'))) AS served_ok
        FROM turns t
        LEFT JOIN LATERAL (
            SELECT min(i.received_at) AS received_at FROM inbox_messages i WHERE i.turn_id = t.id
        ) first_in ON true
        LEFT JOIN LATERAL (
            SELECT min(o.sent_at) AS sent_at FROM outbox_messages o WHERE o.turn_id = t.id
        ) first_out ON true
        LEFT JOIN LATERAL (
            SELECT sum(s.cost_usd) AS cost_usd FROM turn_steps s WHERE s.turn_id = t.id
        ) steps ON true
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW turn_metrics")
