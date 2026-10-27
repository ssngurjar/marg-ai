"""NudgeSchedule: when the daily khoj message is due, in India time (s10b §4.11). Pure.

The parent picks a time of day (8:00 or 18:00 IST). Nothing is sent in quiet hours (20:00 to
07:00 IST), and a parent who already had a khoj turn today doesn't get one.
"""

from datetime import datetime, time, timedelta
from typing import ClassVar
from zoneinfo import ZoneInfo


class NudgeSchedule:
    INDIA: ClassVar[ZoneInfo] = ZoneInfo("Asia/Kolkata")
    QUIET_START: ClassVar[time] = time(20, 0)  # NUDGE_QUIET_START
    QUIET_END: ClassVar[time] = time(7, 0)  # NUDGE_QUIET_END

    @staticmethod
    def next_due(local_time: time, now: datetime) -> datetime:
        """The next moment strictly after `now` when it is `local_time` in India (aware UTC)."""
        if now.tzinfo is None:
            raise ValueError("NudgeSchedule needs an aware datetime")
        local_now = now.astimezone(NudgeSchedule.INDIA)
        candidate = datetime.combine(local_now.date(), local_time, NudgeSchedule.INDIA)
        if candidate <= local_now:
            candidate = datetime.combine(
                local_now.date() + timedelta(days=1), local_time, NudgeSchedule.INDIA
            )
        return candidate.astimezone(now.tzinfo)

    @staticmethod
    def in_quiet_hours(now: datetime) -> bool:
        local = now.astimezone(NudgeSchedule.INDIA).time()
        return local >= NudgeSchedule.QUIET_START or local < NudgeSchedule.QUIET_END

    @staticmethod
    def start_of_india_day(now: datetime) -> datetime:
        """Midnight in India today, as an aware datetime in `now`'s zone."""
        local_now = now.astimezone(NudgeSchedule.INDIA)
        midnight = datetime.combine(local_now.date(), time(0, 0), NudgeSchedule.INDIA)
        return midnight.astimezone(now.tzinfo)
