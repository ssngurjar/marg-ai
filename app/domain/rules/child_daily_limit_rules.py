"""ChildDailyLimitRules: each child's daily talk limit, across all their sessions (s10b §4.16).

Pure. How long a child may talk to Marg.ai in a day, and how long they have.

The session limits (ChildSessionLimits) keep each conversation short; this keeps the day short,
so a child can't talk all day, one session after each cooldown. A parent picks a DailyTalkLimit
for each child, or no limit; until they do, DEFAULT applies. The day is India's, from midnight
IST (as for the daily khoj), and a session belongs to the day it started in.

A session counts from its start to its end, and while it is open, to now, never more than the
session time limit (owner, 2026-11-13: start to end, with the 10-minute cap). A session the
child left without a goodbye is closed as EXPIRED by maintenance some time later, so it counts
only until its last answered question, plus at least a minute for that answer: otherwise a child
could ask one question, walk away, and never use up the day (owner, 2026-11-13). A session in
which the child asked nothing counts nothing, as for the cooldown (owner, 2026-10-29).
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import ClassVar, assert_never

from app.domain.enums import ChildSessionEndReason, DailyTalkLimit
from app.domain.models.child_session import ChildSessionSpan, DailyTalkTime
from app.domain.models.learner import Learner, LearnerId
from app.domain.rules.child_session_rules import ChildSessionLimits
from app.domain.rules.nudge_schedule import NudgeSchedule


class ChildDailyLimitRules:
    DEFAULT: ClassVar[DailyTalkLimit] = DailyTalkLimit.MINUTES_30
    """For a child whose parent hasn't picked (every child consented before the limit existed)."""
    LAST_ANSWER_COUNTS: ClassVar[timedelta] = timedelta(minutes=1)
    """The least a session the child walked away from counts after its last answer."""

    @staticmethod
    def chosen(learner: Learner) -> DailyTalkLimit:
        """The parent's pick for the child, else DEFAULT."""
        return ChildDailyLimitRules.picked_or_default(learner.child_talk_daily_limit)

    @staticmethod
    def picked_or_default(picked: DailyTalkLimit | None) -> DailyTalkLimit:
        return ChildDailyLimitRules.DEFAULT if picked is None else picked

    @staticmethod
    def limit_for(learner: Learner) -> timedelta | None:
        """The child's time a day. None: no limit."""
        return ChildDailyLimitRules.time_allowed(ChildDailyLimitRules.chosen(learner))

    @staticmethod
    def time_allowed(limit: DailyTalkLimit) -> timedelta | None:
        match limit:
            case DailyTalkLimit.MINUTES_20:
                return timedelta(minutes=20)
            case DailyTalkLimit.MINUTES_30:
                return timedelta(minutes=30)
            case DailyTalkLimit.MINUTES_60:
                return timedelta(minutes=60)
            case DailyTalkLimit.NO_LIMIT:
                return None
            case _:
                assert_never(limit)

    @staticmethod
    def day_started(now: datetime) -> datetime:
        """Midnight IST today: the sessions started since then are today's."""
        ChildDailyLimitRules._require_aware(now)
        return NudgeSchedule.start_of_india_day(now)

    @staticmethod
    def read_since(now: datetime) -> datetime:
        """From when a turn reads sessions: yesterday's midnight, so a session that ran over
        midnight can still be summed up with the rest of its own day."""
        return ChildDailyLimitRules.day_started(now) - timedelta(days=1)

    @staticmethod
    def used_today(
        learner_id: LearnerId,
        sessions: Sequence[ChildSessionSpan],
        now: datetime,
        limits: ChildSessionLimits,
    ) -> timedelta:
        """How long this child has talked today, across all their sessions. Other children's
        sessions, and sessions from an earlier day, are left out."""
        return ChildDailyLimitRules.used_that_day(learner_id, sessions, now, now, limits)

    @staticmethod
    def used_that_day(
        learner_id: LearnerId,
        sessions: Sequence[ChildSessionSpan],
        day_of: datetime,
        until: datetime,
        limits: ChildSessionLimits,
    ) -> timedelta:
        """How long this child talked in the sessions started on the India day of `day_of`,
        counted up to `until`: what a parent's summary for a session started at `day_of` and
        ended at `until` reports. A session belongs whole to the day it started, so one that
        ran over midnight, or is summed up after it, still counts there."""
        day_started = ChildDailyLimitRules.day_started(day_of)
        day_ended = day_started + timedelta(days=1)
        used = timedelta(0)
        for session in sessions:
            that_day = day_started <= session.started_at < day_ended
            if session.learner_id == learner_id and that_day:
                used += ChildDailyLimitRules._counted(session, until, limits)
        return used

    @staticmethod
    def is_reached(
        learner: Learner,
        sessions: Sequence[ChildSessionSpan],
        now: datetime,
        limits: ChildSessionLimits,
    ) -> bool:
        """The child has used all of today's time (exactly at the limit counts as reached, as
        for the session time limit). Never, for a child with no limit."""
        allowed = ChildDailyLimitRules.limit_for(learner)
        if allowed is None:
            return False
        return ChildDailyLimitRules.used_today(learner.id, sessions, now, limits) >= allowed

    @staticmethod
    def talk_time(
        learner: Learner,
        sessions: Sequence[ChildSessionSpan],
        day_of: datetime,
        until: datetime,
        limits: ChildSessionLimits,
    ) -> DailyTalkTime:
        """The parent's summary of a session started at `day_of` and ended at `until`: the
        child's time that day, and their limit."""
        used = ChildDailyLimitRules.used_that_day(learner.id, sessions, day_of, until, limits)
        return DailyTalkTime(used=used, limit=ChildDailyLimitRules.chosen(learner))

    @staticmethod
    def is_used_up(talk_time: DailyTalkTime) -> bool:
        """The day's time is all used (never, with no limit)."""
        allowed = ChildDailyLimitRules.time_allowed(talk_time.limit)
        return allowed is not None and talk_time.used >= allowed

    @staticmethod
    def minutes_left_shown(talk_time: DailyTalkTime) -> int | None:
        """Whole minutes left today, from the minutes shown as used, so the two always add up to
        the limit in what the parent reads (14 used of 30 → 16 left). 0 when used up, or under a
        minute left; None: no limit."""
        allowed = ChildDailyLimitRules.time_allowed(talk_time.limit)
        if allowed is None:
            return None
        allowed_minutes = int(allowed.total_seconds() // 60)
        return max(allowed_minutes - ChildDailyLimitRules.whole_minutes(talk_time.used), 0)

    @staticmethod
    def whole_minutes(used: timedelta) -> int:
        """Minutes as a parent reads them: rounded half up (2m30s is 3), 0 under a minute."""
        if used < timedelta(minutes=1):
            return 0
        minutes, seconds = divmod(int(used.total_seconds()), 60)
        return minutes + 1 if seconds >= 30 else minutes  # noqa: PLR2004  # half a minute

    @staticmethod
    def _counted(session: ChildSessionSpan, now: datetime, limits: ChildSessionLimits) -> timedelta:
        if session.turns_count == 0:
            return timedelta(0)
        session_time_up = session.started_at + limits.max_duration
        talk_ended = ChildDailyLimitRules._talk_ended(session, now)
        counted_until = min(talk_ended, session_time_up, now)
        if counted_until <= session.started_at:
            return timedelta(0)  # the database's clock ran a little ahead of the worker's
        return counted_until - session.started_at

    @staticmethod
    def _talk_ended(session: ChildSessionSpan, now: datetime) -> datetime:
        if session.ended_at is None:
            return now  # still open: the child is talking now
        if session.end_reason is not ChildSessionEndReason.EXPIRED:
            return session.ended_at  # ended by a message: a goodbye, a limit, the parent
        if session.last_answered_at is None:
            return session.started_at  # from before answers were recorded: counts nothing
        # left without a goodbye: the talk ended with the last answer (and a minute to hear
        # it), not when maintenance closed the session
        return session.last_answered_at + ChildDailyLimitRules.LAST_ANSWER_COUNTS

    @staticmethod
    def _require_aware(now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("ChildDailyLimitRules needs an aware datetime")
