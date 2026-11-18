"""ChildDailyLimitRules: a parent's daily limit on each child's own talk, counted across all of
that child's sessions in the India day (s10b §4.16; owner, 2026-11-13): each session from start
to end with the 10-minute cap; one the child walked away from until its last answer, plus at
least a minute."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from random import Random

import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from app.domain.enums import ChildSessionEndReason, DailyTalkLimit
from app.domain.models.child_session import ChildSessionSpan, DailyTalkTime
from app.domain.models.learner import Learner, LearnerId
from app.domain.models.writes import ChildTalkDailyLimit, TurnWrite
from app.domain.rules.child_daily_limit_rules import ChildDailyLimitRules
from app.domain.rules.nudge_schedule import NudgeSchedule
from tests.support.child_talk import LIMITS, consented_child

pytestmark = pytest.mark.unit

IST = NudgeSchedule.INDIA
MUNNI = consented_child(1, "Munni")
SESSION_MAX = LIMITS.max_duration  # 10 minutes
A_MINUTE = timedelta(minutes=1)
GOLU = consented_child(2, "Golu", age=7)
ENDED_IN_A_TURN = [
    ChildSessionEndReason.TURN_LIMIT,
    ChildSessionEndReason.TIME_LIMIT,
    ChildSessionEndReason.CHILD_ENDED,
    ChildSessionEndReason.CRISIS,
    ChildSessionEndReason.DAILY_LIMIT,
]


def ist(hour: int, minute: int = 0, *, day: int = 27) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=IST).astimezone(UTC)


NOON = ist(12)


def span(  # noqa: PLR0913  # one keyword per part of a session a test sets
    started: datetime,
    minutes: float | None,
    *,
    turns: int = 2,
    learner: Learner = MUNNI,
    reason: ChildSessionEndReason = ChildSessionEndReason.CHILD_ENDED,
    answered_after: float | None = None,
) -> ChildSessionSpan:
    """A session that ended `minutes` after it started (None: still open), its last question
    answered `answered_after` minutes in (default: as it ended, or one minute in if open)."""
    ended = None if minutes is None else started + timedelta(minutes=minutes)
    if answered_after is not None:
        answered: datetime | None = started + timedelta(minutes=answered_after)
    else:
        answered = ended if ended is not None else started + timedelta(minutes=1)
    return ChildSessionSpan(
        learner_id=learner.id,
        started_at=started,
        ended_at=ended,
        end_reason=None if ended is None else reason,
        last_answered_at=answered if turns else None,
        turns_count=turns,
    )


def with_limit(learner: Learner, limit: DailyTalkLimit | None) -> Learner:
    return learner.model_copy(update={"child_talk_daily_limit": limit})


def used(sessions: Sequence[ChildSessionSpan], now: datetime = NOON) -> timedelta:
    return ChildDailyLimitRules.used_today(MUNNI.id, sessions, now, LIMITS)


def reached(learner: Learner, sessions: Sequence[ChildSessionSpan], now: datetime = NOON) -> bool:
    return ChildDailyLimitRules.is_reached(learner, sessions, now, LIMITS)


def walked_away(started: datetime, answered_after: float) -> ChildSessionSpan:
    """A session the child left without a goodbye; maintenance closed it 10.5 minutes in."""
    return span(started, 10.5, reason=ChildSessionEndReason.EXPIRED, answered_after=answered_after)


# --- the limit ------------------------------------------------------------------------------


def test_a_child_whose_parent_hasnt_picked_gets_30_minutes() -> None:
    assert MUNNI.child_talk_daily_limit is None
    assert ChildDailyLimitRules.DEFAULT is DailyTalkLimit.MINUTES_30
    assert ChildDailyLimitRules.limit_for(MUNNI) == timedelta(minutes=30)


@pytest.mark.parametrize(
    ("limit", "minutes"),
    [
        (DailyTalkLimit.MINUTES_20, 20),
        (DailyTalkLimit.MINUTES_30, 30),
        (DailyTalkLimit.MINUTES_60, 60),
    ],
)
def test_the_parents_pick_is_the_childs_time_a_day(limit: DailyTalkLimit, minutes: int) -> None:
    assert ChildDailyLimitRules.limit_for(with_limit(MUNNI, limit)) == timedelta(minutes=minutes)


def test_no_limit_is_never_reached() -> None:
    munni = with_limit(MUNNI, DailyTalkLimit.NO_LIMIT)
    all_day = [span(ist(7 + hour), 10, turns=6) for hour in range(12)]
    assert ChildDailyLimitRules.limit_for(munni) is None
    assert used(all_day, ist(20)) == timedelta(hours=2)  # still counted, never limited
    assert not reached(munni, all_day, ist(20))


def test_every_choice_has_a_time() -> None:
    """A new DailyTalkLimit without a time fails mypy (assert_never); this catches it at run
    time too."""
    for limit in DailyTalkLimit:
        allowed = ChildDailyLimitRules.time_allowed(limit)
        assert (allowed is None) == (limit is DailyTalkLimit.NO_LIMIT)


def test_each_child_has_their_own_limit() -> None:
    munni = with_limit(MUNNI, DailyTalkLimit.MINUTES_20)
    golu = with_limit(GOLU, DailyTalkLimit.MINUTES_60)
    assert ChildDailyLimitRules.limit_for(munni) == timedelta(minutes=20)
    assert ChildDailyLimitRules.limit_for(golu) == timedelta(minutes=60)


# --- counting the day's time ----------------------------------------------------------------


def test_no_sessions_today_is_no_time_used() -> None:
    assert used([]) == timedelta(0)


def test_every_session_today_counts_not_only_the_latest() -> None:
    """The point of the daily limit: one session after another, each after a cooldown."""
    sessions = [span(ist(8), 10), span(ist(9), 4), span(ist(10), 7)]
    assert used(sessions) == timedelta(minutes=21)


@pytest.mark.parametrize("reason", ENDED_IN_A_TURN)
def test_a_session_counts_from_its_start_to_its_end(reason: ChildSessionEndReason) -> None:
    """Owner, 2026-11-13: start to end. The end came with a message the child sent."""
    sessions = [span(ist(9), 7.5, reason=reason, answered_after=6)]
    assert used(sessions) == timedelta(minutes=7.5)


@pytest.mark.parametrize("reason", [*ENDED_IN_A_TURN, ChildSessionEndReason.EXPIRED])
def test_a_session_never_counts_more_than_the_10_minute_cap(
    reason: ChildSessionEndReason,
) -> None:
    """Owner, 2026-11-13: the 10-minute cap stays. A TIME_LIMIT goodbye comes with the child's
    next message, which can be well after the time was up."""
    ended_late = span(ist(9), 35, reason=reason, answered_after=34)
    assert used([ended_late]) == SESSION_MAX


def test_an_open_session_past_the_time_limit_counts_10_minutes() -> None:
    assert used([span(NOON - timedelta(minutes=25), None)]) == SESSION_MAX


def test_a_session_the_child_walked_away_from_counts_until_its_last_answer_and_a_minute() -> None:
    """Owner, 2026-11-13: not the full 10 minutes, nor until maintenance closed it; the last
    answer counts at least a minute."""
    assert used([walked_away(ist(9), answered_after=4)]) == timedelta(minutes=5)


def test_one_question_then_walking_away_counts_a_minute() -> None:
    """The opening message is answered as the session starts: without the minute it would
    count nothing (owner, 2026-11-13)."""
    assert used([walked_away(ist(9), answered_after=0)]) == A_MINUTE


def test_asking_one_question_and_walking_away_all_day_still_uses_up_the_day() -> None:
    """The gap the minute closes: each such talk counts, so the limit is reached."""
    one_question_talks = [
        walked_away(ist(5) + timedelta(minutes=35 * number), answered_after=0)
        for number in range(30)
    ]
    evening = ist(23)
    assert used(one_question_talks, evening) == timedelta(minutes=30)
    assert reached(MUNNI, one_question_talks, evening)
    assert not reached(MUNNI, one_question_talks[:29], evening)


def test_a_last_answer_near_the_time_limit_still_counts_no_more_than_10_minutes() -> None:
    assert used([walked_away(ist(9), answered_after=9.5)]) == SESSION_MAX


def test_the_minute_is_only_for_a_session_walked_away_from() -> None:
    """A session ended by a message (bye, a limit, the parent) counts to that message."""
    said_bye = span(ist(9), 0.5, reason=ChildSessionEndReason.CHILD_ENDED, answered_after=0)
    assert used([said_bye]) == timedelta(seconds=30)


def test_a_session_from_before_the_last_answer_was_recorded_counts_nothing() -> None:
    old = ChildSessionSpan(
        learner_id=MUNNI.id,
        started_at=ist(9),
        ended_at=ist(9, 11),
        end_reason=ChildSessionEndReason.EXPIRED,
        last_answered_at=None,
        turns_count=3,
    )
    assert used([old]) == timedelta(0)


def test_the_open_session_counts_up_to_now() -> None:
    sessions = [span(ist(9), 10), span(NOON - timedelta(minutes=3), None)]
    assert used(sessions) == timedelta(minutes=13)


@pytest.mark.parametrize("minutes", [None, 0.5, 10])
def test_a_session_in_which_nothing_was_asked_counts_nothing(minutes: float | None) -> None:
    """As for the cooldown (owner, 2026-10-29): a hello and nothing more used no screen time."""
    assert used([span(ist(11), minutes, turns=0)]) == timedelta(0)


def test_another_childs_sessions_are_not_counted() -> None:
    sessions = [span(ist(9), 10, learner=GOLU), span(ist(10), 5)]
    assert used(sessions) == timedelta(minutes=5)
    assert ChildDailyLimitRules.used_today(GOLU.id, sessions, NOON, LIMITS) == timedelta(minutes=10)


def test_yesterdays_sessions_are_not_counted() -> None:
    assert used([span(ist(19, day=26), 10)]) == timedelta(0)


def test_a_session_belongs_to_the_day_it_started() -> None:
    """Start to end only: a session over midnight is not split between the days."""
    over_midnight = span(ist(23, 55, day=26), 10)
    assert used([over_midnight], now=ist(23, 59, day=26)) == timedelta(minutes=4)
    assert used([over_midnight], now=ist(8)) == timedelta(0)


def test_the_india_day_not_the_utc_day_decides() -> None:
    """18:00 UTC on the 26th is 23:30 IST on the 26th; 19:00 UTC is 00:30 IST on the 27th."""
    before_india_midnight = span(datetime(2026, 10, 26, 18, 0, tzinfo=UTC), 10)
    after_india_midnight = span(datetime(2026, 10, 26, 19, 0, tzinfo=UTC), 10)
    assert used([before_india_midnight, after_india_midnight], now=ist(8)) == timedelta(minutes=10)


def test_a_session_stamped_after_now_counts_nothing() -> None:
    """The database's clock can run a little ahead of the worker's."""
    assert used([span(NOON + timedelta(seconds=2), None)]) == timedelta(0)


def test_the_day_starts_at_midnight_india_time() -> None:
    assert ChildDailyLimitRules.day_started(NOON) == ist(0)


# --- reached --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("limit", "minutes"),
    [
        (DailyTalkLimit.MINUTES_20, 20),
        (DailyTalkLimit.MINUTES_30, 30),
        (DailyTalkLimit.MINUTES_60, 60),
    ],
)
def test_exactly_at_the_limit_is_reached_and_a_second_under_is_not(
    limit: DailyTalkLimit, minutes: int
) -> None:
    munni = with_limit(MUNNI, limit)
    full_sessions = [span(ist(6, 0) + timedelta(minutes=35 * n), 10) for n in range(minutes // 10)]
    one_short = span(full_sessions[-1].started_at, 10 - 1 / 60)
    assert reached(munni, full_sessions, NOON)
    assert not reached(munni, [*full_sessions[:-1], one_short], NOON)


def test_the_default_30_minutes_applies_until_the_parent_picks() -> None:
    three_sessions = [span(ist(8), 10), span(ist(9), 10), span(ist(10), 10)]
    assert reached(MUNNI, three_sessions[:3], NOON)
    assert not reached(MUNNI, three_sessions[:2], NOON)


def test_an_open_session_reaches_the_limit_while_it_runs() -> None:
    munni = with_limit(MUNNI, DailyTalkLimit.MINUTES_20)
    opened = NOON - timedelta(minutes=10)
    sessions = [span(ist(8), 14), span(opened, None)]  # the first counts 10
    assert not reached(munni, sessions, opened + timedelta(minutes=9))
    assert reached(munni, sessions, opened + timedelta(minutes=10))


def test_the_limit_is_fresh_the_next_india_day() -> None:
    munni = with_limit(MUNNI, DailyTalkLimit.MINUTES_20)
    yesterday = [span(ist(19, day=26), 10), span(ist(20, day=26), 10)]
    assert reached(munni, yesterday, ist(20, 30, day=26))
    assert not reached(munni, yesterday, ist(0, 0, day=27))


def test_another_child_using_up_their_time_leaves_this_childs_alone() -> None:
    golu_morning = [span(ist(8 + hour), 10, learner=GOLU) for hour in range(3)]
    assert reached(GOLU, golu_morning, NOON)
    assert not reached(MUNNI, golu_morning, NOON)


# --- wrong and missing input ----------------------------------------------------------------


def test_a_naive_now_is_refused() -> None:
    naive = datetime(2026, 10, 27, 12, 0)  # noqa: DTZ001  # the naive input under test
    with pytest.raises(ValueError, match="aware datetime"):
        ChildDailyLimitRules.used_today(MUNNI.id, [], naive, LIMITS)
    with pytest.raises(ValueError, match="aware datetime"):
        ChildDailyLimitRules.day_started(naive)
    with pytest.raises(ValueError, match="aware datetime"):
        ChildDailyLimitRules.is_reached(MUNNI, [], naive, LIMITS)


def test_a_session_with_a_naive_time_is_refused() -> None:
    naive = datetime(2026, 10, 27, 9, 0)  # noqa: DTZ001  # the naive input under test
    fields: dict[str, object] = {
        "learner_id": MUNNI.id,
        "started_at": NOON,
        "ended_at": None,
        "end_reason": None,
        "last_answered_at": None,
        "turns_count": 1,
    }
    for field in ("started_at", "last_answered_at"):
        with pytest.raises(ValidationError, match="timezone"):
            ChildSessionSpan.model_validate({**fields, field: naive})


def test_a_session_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(ValidationError, match="can't end before it starts"):
        span(NOON, -1)


def test_a_session_answered_before_it_starts_is_refused() -> None:
    with pytest.raises(ValidationError, match="can't answer before it starts"):
        span(NOON, 5, answered_after=-1)


@pytest.mark.parametrize(
    ("ended", "reason"),
    [(None, ChildSessionEndReason.EXPIRED), (NOON + timedelta(minutes=5), None)],
)
def test_an_end_time_without_a_reason_or_a_reason_without_one_is_refused(
    ended: datetime | None, reason: ChildSessionEndReason | None
) -> None:
    with pytest.raises(ValidationError, match="end time exactly when it has an end reason"):
        ChildSessionSpan(
            learner_id=MUNNI.id,
            started_at=NOON,
            ended_at=ended,
            end_reason=reason,
            last_answered_at=None,
            turns_count=1,
        )


@pytest.mark.parametrize("turns", [-1, None, "two", 2.5])
def test_a_session_with_a_bad_turn_count_is_refused(turns: object) -> None:
    with pytest.raises(ValidationError, match="turns_count"):
        ChildSessionSpan.model_validate(
            {
                "learner_id": MUNNI.id,
                "started_at": NOON,
                "ended_at": None,
                "end_reason": None,
                "last_answered_at": None,
                "turns_count": turns,
            }
        )


# --- the write that stores the parent's pick ------------------------------------------------


@pytest.mark.parametrize("limit", list(DailyTalkLimit))
def test_the_parents_pick_is_a_turn_write(limit: DailyTalkLimit) -> None:
    write = ChildTalkDailyLimit(learner_id=MUNNI.id, limit=limit)
    parsed = TypeAdapter(TurnWrite).validate_python(write.model_dump())
    assert parsed == write


@pytest.mark.parametrize(
    "limit", ["10_minutes", "45_minutes", "no limit", "NO_LIMIT", "", 30, None, True]
)
def test_a_limit_that_isnt_one_of_the_choices_is_refused(limit: object) -> None:
    with pytest.raises(ValidationError, match="limit"):
        ChildTalkDailyLimit.model_validate({"learner_id": MUNNI.id, "limit": limit})


def test_a_learner_cant_carry_a_limit_outside_the_choices() -> None:
    with pytest.raises(ValidationError, match="child_talk_daily_limit"):
        Learner.model_validate({**MUNNI.model_dump(), "child_talk_daily_limit": "45_minutes"})


def test_the_write_needs_a_child() -> None:
    with pytest.raises(ValidationError, match="learner_id"):
        ChildTalkDailyLimit.model_validate({"limit": DailyTalkLimit.MINUTES_20})


# --- properties -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _PlannedSession:
    gap_before: timedelta  # from the end of the previous session (or from `first_start`)
    length: timedelta | None  # None: still open (only the last one can be)
    answered_share: float  # how far into the session the last question was answered
    turns: int
    reason: ChildSessionEndReason


_planned_sessions = st.lists(
    st.builds(
        _PlannedSession,
        gap_before=st.timedeltas(timedelta(0), timedelta(hours=6)),
        length=st.one_of(st.none(), st.timedeltas(timedelta(0), timedelta(hours=2))),
        answered_share=st.floats(0, 1),
        turns=st.integers(0, 6),
        reason=st.sampled_from(ChildSessionEndReason),
    ),
    max_size=8,
)
_first_starts = st.datetimes(
    min_value=datetime(2026, 10, 25),  # noqa: DTZ001  # Hypothesis takes naive bounds
    max_value=datetime(2026, 10, 28),  # noqa: DTZ001  # with an aware timezone strategy
    timezones=st.just(UTC),
)


@dataclass(frozen=True, slots=True)
class _Day:
    sessions: list[ChildSessionSpan]
    now: datetime


def _one_childs_day(
    first_start: datetime, planned: Sequence[_PlannedSession], learner: LearnerId
) -> _Day:
    """Sessions one after another, as one account allows (never two open at once); `now` is
    a minute after the last one ends. Maintenance closes a session as EXPIRED only once its
    time is up, so an expired one runs at least the session time limit."""
    sessions: list[ChildSessionSpan] = []
    start = first_start
    for number, plan in enumerate(planned):
        start += plan.gap_before
        is_last = number == len(planned) - 1
        length = plan.length if plan.length is not None or is_last else timedelta(minutes=5)
        if length is not None and plan.reason is ChildSessionEndReason.EXPIRED:
            length = max(length, SESSION_MAX + timedelta(seconds=30))
        ended = None if length is None else start + length
        answered = start + (length or timedelta(minutes=1)) * plan.answered_share
        sessions.append(
            ChildSessionSpan(
                learner_id=learner,
                started_at=start,
                ended_at=ended,
                end_reason=None if ended is None else plan.reason,
                last_answered_at=answered if plan.turns else None,
                turns_count=plan.turns,
            )
        )
        start = start if ended is None else ended
    return _Day(sessions=sessions, now=start + timedelta(minutes=1))


@given(first_start=_first_starts, planned=_planned_sessions)
@example(
    first_start=ist(23, 55, day=26),
    planned=[_PlannedSession(timedelta(0), None, 1.0, 1, ChildSessionEndReason.EXPIRED)],
)
def test_the_time_used_never_goes_below_zero_or_past_the_day_so_far(
    first_start: datetime, planned: list[_PlannedSession]
) -> None:
    day = _one_childs_day(first_start, planned, MUNNI.id)
    total = used(day.sessions, day.now)
    assert timedelta(0) <= total <= day.now - ChildDailyLimitRules.day_started(day.now)


@given(first_start=_first_starts, planned=_planned_sessions)
def test_a_session_never_counts_more_than_it_ran(
    first_start: datetime, planned: list[_PlannedSession]
) -> None:
    day = _one_childs_day(first_start, planned, MUNNI.id)
    for session in day.sessions:
        ran_until = session.ended_at or day.now
        assert used([session], day.now) <= ran_until - session.started_at


@given(first_start=_first_starts, planned=_planned_sessions)
def test_no_session_counts_more_than_the_session_time_limit(
    first_start: datetime, planned: list[_PlannedSession]
) -> None:
    day = _one_childs_day(first_start, planned, MUNNI.id)
    for session in day.sessions:
        assert used([session], day.now) <= SESSION_MAX


@given(first_start=_first_starts, planned=_planned_sessions)
def test_a_session_walked_away_from_after_an_answer_counts_at_least_a_minute(
    first_start: datetime, planned: list[_PlannedSession]
) -> None:
    """Owner, 2026-11-13: one question and walking away can't be free."""
    day = _one_childs_day(first_start, planned, MUNNI.id)
    today_started = ChildDailyLimitRules.day_started(day.now)
    for session in day.sessions:
        walked_away_today = (
            session.end_reason is ChildSessionEndReason.EXPIRED
            and session.turns_count > 0
            and session.started_at >= today_started
        )
        if walked_away_today:
            assert used([session], day.now) >= A_MINUTE


@given(
    first_start=_first_starts,
    planned=_planned_sessions,
    shuffler=st.randoms(use_true_random=False),
)
def test_the_order_sessions_arrive_in_doesnt_matter(
    first_start: datetime, planned: list[_PlannedSession], shuffler: Random
) -> None:
    day = _one_childs_day(first_start, planned, MUNNI.id)
    shuffled = list(day.sessions)
    shuffler.shuffle(shuffled)
    assert used(shuffled, day.now) == used(day.sessions, day.now)


@given(
    first_start=_first_starts,
    planned=_planned_sessions,
    other_start=_first_starts,
    other_planned=_planned_sessions,
)
def test_another_childs_sessions_never_change_this_childs_time(
    first_start: datetime,
    planned: list[_PlannedSession],
    other_start: datetime,
    other_planned: list[_PlannedSession],
) -> None:
    munni_day = _one_childs_day(first_start, planned, MUNNI.id)
    golu_day = _one_childs_day(other_start, other_planned, GOLU.id)
    both = [*munni_day.sessions, *golu_day.sessions]
    assert used(both, munni_day.now) == used(munni_day.sessions, munni_day.now)


@given(first_start=_first_starts, planned=_planned_sessions)
def test_a_session_that_asked_nothing_never_adds_time(
    first_start: datetime, planned: list[_PlannedSession]
) -> None:
    day = _one_childs_day(first_start, planned, MUNNI.id)
    asked_something = [session for session in day.sessions if session.turns_count > 0]
    assert used(day.sessions, day.now) == used(asked_something, day.now)


@given(
    first_start=_first_starts,
    planned=_planned_sessions,
    later=st.timedeltas(timedelta(0), timedelta(hours=30)),
)
def test_within_one_india_day_the_time_used_only_grows(
    first_start: datetime, planned: list[_PlannedSession], later: timedelta
) -> None:
    day = _one_childs_day(first_start, planned, MUNNI.id)
    last_moment_today = (
        ChildDailyLimitRules.day_started(day.now) + timedelta(days=1) - timedelta(microseconds=1)
    )
    then = min(day.now + later, last_moment_today)
    assert used(day.sessions, then) >= used(day.sessions, day.now)


@given(first_start=_first_starts, planned=_planned_sessions)
def test_only_sessions_started_today_are_needed(
    first_start: datetime, planned: list[_PlannedSession]
) -> None:
    """What the store reads (started since `day_started`) is all the rule needs."""
    day = _one_childs_day(first_start, planned, MUNNI.id)
    since = ChildDailyLimitRules.day_started(day.now)
    read = [session for session in day.sessions if session.started_at >= since]
    assert used(read, day.now) == used(day.sessions, day.now)


@given(
    limit=st.sampled_from(DailyTalkLimit),
    first_start=_first_starts,
    planned=_planned_sessions,
)
def test_is_reached_is_the_time_used_against_the_limit(
    limit: DailyTalkLimit, first_start: datetime, planned: list[_PlannedSession]
) -> None:
    munni = with_limit(MUNNI, limit)
    day = _one_childs_day(first_start, planned, MUNNI.id)
    allowed = ChildDailyLimitRules.time_allowed(limit)
    expected = allowed is not None and used(day.sessions, day.now) >= allowed
    assert reached(munni, day.sessions, day.now) is expected


# --- the time in the parent's summary (owner, 2026-11-13) -----------------------------------


def test_the_summary_of_a_session_over_midnight_reports_the_day_it_started() -> None:
    earlier_that_evening = span(ist(21, day=26), 10)
    over_midnight = span(ist(23, 55, day=26), None)
    sessions = [earlier_that_evening, over_midnight]
    at_goodbye = ist(0, 4)
    used = ChildDailyLimitRules.used_that_day(
        MUNNI.id, sessions, over_midnight.started_at, at_goodbye, LIMITS
    )
    assert used == timedelta(minutes=19)  # 10, and its 9 minutes, over midnight too
    assert used_today_at(sessions, at_goodbye) == timedelta(0)  # the new day has none yet


def used_today_at(sessions: Sequence[ChildSessionSpan], now: datetime) -> timedelta:
    return ChildDailyLimitRules.used_today(MUNNI.id, sessions, now, LIMITS)


def test_the_summary_counts_only_up_to_the_sessions_end() -> None:
    left = walked_away(ist(9), answered_after=3)
    later_that_day = span(ist(15), 10)
    used = ChildDailyLimitRules.used_that_day(
        MUNNI.id, [left, later_that_day], left.started_at, left.ended_at or NOON, LIMITS
    )
    assert used == timedelta(minutes=4)


def test_a_turn_reads_sessions_from_yesterdays_midnight() -> None:
    assert ChildDailyLimitRules.read_since(NOON) == ist(0, day=26)


def test_talk_time_is_the_days_time_and_the_childs_limit() -> None:
    munni = with_limit(MUNNI, DailyTalkLimit.MINUTES_60)
    talk_time = ChildDailyLimitRules.talk_time(munni, [span(ist(9), 7)], NOON, NOON, LIMITS)
    assert talk_time.used == timedelta(minutes=7)
    assert talk_time.limit is DailyTalkLimit.MINUTES_60
    assert ChildDailyLimitRules.talk_time(MUNNI, [], NOON, NOON, LIMITS).limit is (
        DailyTalkLimit.MINUTES_30
    )


@pytest.mark.parametrize(
    ("used", "limit"),
    [
        (timedelta(minutes=30), DailyTalkLimit.MINUTES_30),
        (timedelta(minutes=31), DailyTalkLimit.MINUTES_30),
        (timedelta(minutes=60), DailyTalkLimit.MINUTES_60),
    ],
)
def test_at_or_past_the_limit_is_used_up(used: timedelta, limit: DailyTalkLimit) -> None:
    assert ChildDailyLimitRules.is_used_up(DailyTalkTime(used=used, limit=limit))


@pytest.mark.parametrize(
    ("used", "limit"),
    [
        (timedelta(minutes=29, seconds=59), DailyTalkLimit.MINUTES_30),
        (timedelta(minutes=19), DailyTalkLimit.MINUTES_20),
        (timedelta(hours=5), DailyTalkLimit.NO_LIMIT),
    ],
)
def test_under_the_limit_or_with_none_is_not_used_up(
    used: timedelta, limit: DailyTalkLimit
) -> None:
    assert not ChildDailyLimitRules.is_used_up(DailyTalkTime(used=used, limit=limit))


@pytest.mark.parametrize(
    ("used", "minutes"),
    [
        (timedelta(0), 0),
        (timedelta(seconds=59), 0),
        (timedelta(minutes=1), 1),
        (timedelta(minutes=1, seconds=29), 1),
        (timedelta(minutes=1, seconds=30), 2),
        (timedelta(minutes=2, seconds=30), 3),  # half up, not to the even 2
        (timedelta(minutes=10), 10),
        (timedelta(minutes=29, seconds=40), 30),
    ],
)
def test_minutes_are_rounded_half_up_and_none_under_a_minute(used: timedelta, minutes: int) -> None:
    assert ChildDailyLimitRules.whole_minutes(used) == minutes


@given(
    shorter=st.timedeltas(timedelta(0), timedelta(hours=3)),
    more=st.timedeltas(timedelta(0), timedelta(hours=3)),
)
def test_more_time_never_shows_fewer_minutes(shorter: timedelta, more: timedelta) -> None:
    assert ChildDailyLimitRules.whole_minutes(shorter + more) >= ChildDailyLimitRules.whole_minutes(
        shorter
    )


@given(used=st.timedeltas(timedelta(minutes=1), timedelta(hours=5)))
def test_the_minutes_shown_are_within_half_a_minute(used: timedelta) -> None:
    shown = timedelta(minutes=ChildDailyLimitRules.whole_minutes(used))
    assert abs(shown - used) <= timedelta(seconds=30)


def test_a_negative_time_used_is_refused() -> None:
    with pytest.raises(ValidationError, match="used"):
        DailyTalkTime(used=timedelta(seconds=-1), limit=DailyTalkLimit.MINUTES_30)


# --- time left today, as the parent reads it (owner, 2026-11-13) --------------------------------


@pytest.mark.parametrize(
    ("used", "limit", "left"),
    [
        (timedelta(0), DailyTalkLimit.MINUTES_30, 30),
        (timedelta(minutes=14), DailyTalkLimit.MINUTES_30, 16),
        (timedelta(minutes=14, seconds=30), DailyTalkLimit.MINUTES_30, 15),  # 15 shown used
        (timedelta(minutes=25), DailyTalkLimit.MINUTES_60, 35),
        (timedelta(minutes=29, seconds=40), DailyTalkLimit.MINUTES_30, 0),  # under a minute
        (timedelta(minutes=45), DailyTalkLimit.MINUTES_30, 0),
    ],
)
def test_minutes_left_add_up_with_the_minutes_shown_to_the_limit(
    used: timedelta, limit: DailyTalkLimit, left: int
) -> None:
    talk_time = DailyTalkTime(used=used, limit=limit)
    assert ChildDailyLimitRules.minutes_left_shown(talk_time) == left


def test_with_no_limit_nothing_is_left_to_count() -> None:
    talk_time = DailyTalkTime(used=timedelta(minutes=90), limit=DailyTalkLimit.NO_LIMIT)
    assert ChildDailyLimitRules.minutes_left_shown(talk_time) is None


@given(
    used=st.timedeltas(timedelta(0), timedelta(hours=2)),
    limit=st.sampled_from(
        [DailyTalkLimit.MINUTES_20, DailyTalkLimit.MINUTES_30, DailyTalkLimit.MINUTES_60]
    ),
)
def test_shown_used_and_left_never_add_up_past_the_limit(
    used: timedelta, limit: DailyTalkLimit
) -> None:
    talk_time = DailyTalkTime(used=used, limit=limit)
    left = ChildDailyLimitRules.minutes_left_shown(talk_time)
    allowed = ChildDailyLimitRules.time_allowed(limit)
    assert left is not None
    assert allowed is not None
    shown_used = ChildDailyLimitRules.whole_minutes(used)
    allowed_minutes = int(allowed.total_seconds() // 60)
    assert 0 <= left <= allowed_minutes
    if shown_used <= allowed_minutes:
        assert shown_used + left == allowed_minutes
