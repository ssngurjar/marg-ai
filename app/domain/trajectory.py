"""The learner's journey over time. S4 adds the session rule; S13 adds the trajectory metrics."""

from datetime import datetime, timedelta
from typing import Final

SESSION_GAP: Final = timedelta(hours=6)
"""The only definition of a session: a gap longer than this between turns starts a new one."""


def is_session_start(previous_turn_started_at: datetime | None, first_message_at: datetime) -> bool:
    """True for a user's first turn, or when more than SESSION_GAP has passed since the last."""
    if previous_turn_started_at is None:
        return True
    return first_message_at - previous_turn_started_at > SESSION_GAP
