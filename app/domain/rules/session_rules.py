"""SessionRules: the only definition of a session (contracts §2.2). Pure."""

from datetime import datetime, timedelta
from typing import ClassVar


class SessionRules:
    SESSION_GAP: ClassVar[timedelta] = timedelta(hours=6)
    """A gap longer than this between turns starts a new session."""

    @staticmethod
    def is_session_start(
        previous_turn_started_at: datetime | None, first_message_at: datetime
    ) -> bool:
        """True for a user's first turn, or after more than SESSION_GAP since the last one."""
        if previous_turn_started_at is None:
            return True
        return first_message_at - previous_turn_started_at > SessionRules.SESSION_GAP
