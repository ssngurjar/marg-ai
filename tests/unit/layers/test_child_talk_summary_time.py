"""The time used, in the parent's summary (s10b §4.16; owner, 2026-11-13): one line under the
topics with the child's time that day across all their talks, and their daily limit. At every
ending that sends a summary (a goodbye, the turn or time limit, the daily limit, the parent
taking the phone back); never after a crisis."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.enums import (
    ChildSessionEndReason,
    CuriosityDomain,
    DailyTalkLimit,
    Language,
)
from app.domain.models.child_session import ChildSessionSpan, DailyTalkTime
from app.domain.models.writes import ChildSessionEnd
from app.domain.rules.child_session_rules import KID_PARENT
from app.domain.rules.nudge_schedule import NudgeSchedule
from app.layers.child_talk_layer import ChildTalkLayer
from tests.fakes.language_model import FakeLanguageModel
from tests.support.child_talk import CHILD_REPLY, LIMITS, consented_child, open_session
from tests.support.prompts import shipped_registry
from tests.support.turn_context import text_message, turn_context
from tests.unit.layers.test_child_talk_daily_limit import (
    MUNNI,
    a_session,
    talk,
    talked_today,
    the_open_one,
)

pytestmark = pytest.mark.unit

H = Language.HINGLISH


def time_line_of(body: str) -> str:
    [line] = [line for line in body.splitlines() if line.startswith("⏱️")]
    return line


# --- at each ending --------------------------------------------------------------------------


async def test_a_goodbye_tells_the_parent_the_days_time_and_the_limit() -> None:
    session = a_session(6)
    result, _ = await talk("bye", session=session, today=[*talked_today(10), the_open_one(session)])
    assert time_line_of(result.reply.body) == "⏱️ Aaj kul baat: 16 minute. Roz ki limit: 30 minute."


async def test_the_time_line_comes_under_the_topics() -> None:
    session = open_session(
        MUNNI, turns=2, started=a_session(6).started_at, topics=[CuriosityDomain.EARTH_SKY]
    )
    result, _ = await talk("bye", session=session, today=[the_open_one(session)])
    lines = result.reply.body.splitlines()
    topics_at = next(n for n, line in enumerate(lines) if line.startswith("👪"))
    assert lines[topics_at + 1].startswith("⏱️")


async def test_when_the_day_runs_out_the_parent_is_told_the_limit_is_used_up() -> None:
    session = a_session(6)
    result, _ = await talk(session=session, today=[*talked_today(24), the_open_one(session)])
    assert time_line_of(result.reply.body) == (
        "⏱️ Aaj kul baat: 30 minute. Roz ki 30 minute ki limit poori ho gayi; kal phir baat kar"
        " sakte hain."
    )


async def test_the_sixth_question_summary_shows_the_parents_pick() -> None:
    munni = MUNNI.model_copy(update={"child_talk_daily_limit": DailyTalkLimit.MINUTES_60})
    session = open_session(munni, turns=5, started=a_session(8).started_at)
    result, _ = await talk(session=session, today=[the_open_one(session)], learners=[munni])
    assert time_line_of(result.reply.body) == "⏱️ Aaj kul baat: 8 minute. Roz ki limit: 1 ghanta."


async def test_with_no_limit_the_summary_says_so() -> None:
    free = MUNNI.model_copy(update={"child_talk_daily_limit": DailyTalkLimit.NO_LIMIT})
    session = open_session(free, turns=2, started=a_session(5).started_at)
    earlier = talked_today(40, learner=free)
    result, _ = await talk(
        "bye", session=session, today=[*earlier, the_open_one(session)], learners=[free]
    )
    assert time_line_of(result.reply.body) == "⏱️ Aaj kul baat: 45 minute. Roz ki koi limit nahi."


async def test_the_parent_taking_the_phone_back_gets_the_time_too() -> None:
    session = a_session(4)
    result, _ = await talk(
        buttons=[KID_PARENT], session=session, today=[*talked_today(10), the_open_one(session)]
    )
    assert time_line_of(result.reply.body) == "⏱️ Aaj kul baat: 14 minute. Roz ki limit: 30 minute."


async def test_a_session_past_its_10_minutes_counts_10_in_the_summary() -> None:
    session = a_session(11)  # ends on the time limit at the child's next message
    result, _ = await talk(session=session, today=[the_open_one(session)])
    ended = result.writes[-1]
    assert isinstance(ended, ChildSessionEnd)
    assert ended.reason is ChildSessionEndReason.TIME_LIMIT
    assert time_line_of(result.reply.body) == "⏱️ Aaj kul baat: 10 minute. Roz ki limit: 30 minute."


async def test_no_summary_and_so_no_time_when_the_child_asked_nothing() -> None:
    session = a_session(3, turns=0)
    result, _ = await talk("bye", session=session, today=[the_open_one(session)])
    assert "⏱️" not in result.reply.body


async def test_a_siblings_time_is_not_in_this_childs_summary() -> None:
    golu = consented_child(2, "Golu", age=7)
    session = a_session(6)
    golu_today = talked_today(30, learner=golu)
    result, _ = await talk(
        "bye", session=session, today=[*golu_today, the_open_one(session)], learners=[MUNNI, golu]
    )
    assert time_line_of(result.reply.body) == "⏱️ Aaj kul baat: 6 minute. Roz ki limit: 30 minute."


async def test_a_session_over_midnight_is_summed_up_with_the_day_it_started() -> None:
    ist = NudgeSchedule.INDIA
    started = datetime(2026, 10, 26, 23, 55, tzinfo=ist).astimezone(UTC)
    goodbye_at = datetime(2026, 10, 27, 0, 4, tzinfo=ist).astimezone(UTC)
    session = open_session(MUNNI, turns=2, started=started)
    earlier_that_evening = ChildSessionSpan(
        learner_id=MUNNI.id,
        started_at=started - timedelta(hours=2),
        ended_at=started - timedelta(hours=2) + timedelta(minutes=10),
        end_reason=ChildSessionEndReason.CHILD_ENDED,
        last_answered_at=started - timedelta(hours=2) + timedelta(minutes=10),
        turns_count=3,
    )
    layer = ChildTalkLayer(FakeLanguageModel([CHILD_REPLY]), shipped_registry(), LIMITS)
    ctx = turn_context(text_message("bye"), learners=[MUNNI]).model_copy(
        update={
            "child_session": session,
            "child_talk_today": [earlier_that_evening, the_open_one(session)],
        }
    )
    result = await layer.handle(ctx, "bye", [], goodbye_at, H)
    assert time_line_of(result.reply.body) == "⏱️ Aaj kul baat: 19 minute. Roz ki limit: 30 minute."


# --- the wording -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("used", "language", "line"),
    [
        (timedelta(seconds=40), H, "⏱️ Aaj kul baat: 1 minute se kam. Roz ki limit: 30 minute."),
        (timedelta(minutes=1), H, "⏱️ Aaj kul baat: 1 minute. Roz ki limit: 30 minute."),
        (
            timedelta(minutes=1),
            Language.ENGLISH,
            "⏱️ Talk today: 1 minute in all. Daily limit: 30 minutes.",
        ),
        (
            timedelta(minutes=12, seconds=31),
            Language.ENGLISH,
            "⏱️ Talk today: 13 minutes in all. Daily limit: 30 minutes.",
        ),
        (timedelta(minutes=12), Language.HINDI, "⏱️ आज कुल बात: 12 मिनट। रोज़ की लिमिट: 30 मिनट।"),
        (
            timedelta(seconds=20),
            Language.HINDI,
            "⏱️ आज कुल बात: 1 मिनट से कम। रोज़ की लिमिट: 30 मिनट।",
        ),
    ],
)
def test_the_time_is_said_in_the_parents_language(
    used: timedelta, language: Language, line: str
) -> None:
    talk_time = DailyTalkTime(used=used, limit=DailyTalkLimit.MINUTES_30)
    summary = ChildTalkLayer.parent_summary("Munni", [], language, talk_time)
    assert time_line_of(summary) == line


@pytest.mark.parametrize(
    ("language", "line"),
    [
        (
            Language.ENGLISH,
            "⏱️ Talk today: 20 minutes in all, so today's limit (20 minutes) is used up; they can"
            " talk again tomorrow.",
        ),
        (
            Language.HINDI,
            "⏱️ आज कुल बात: 20 मिनट। रोज़ की 20 मिनट की लिमिट पूरी हो गई; कल फिर बात कर सकते हैं।",
        ),
    ],
)
def test_used_up_is_said_in_every_language(language: Language, line: str) -> None:
    talk_time = DailyTalkTime(used=timedelta(minutes=20), limit=DailyTalkLimit.MINUTES_20)
    assert time_line_of(ChildTalkLayer.parent_summary("Munni", [], language, talk_time)) == line


@pytest.mark.parametrize("language", list(Language))
@pytest.mark.parametrize("limit", list(DailyTalkLimit))
def test_every_limit_has_a_time_line_in_every_language(
    limit: DailyTalkLimit, language: Language
) -> None:
    talk_time = DailyTalkTime(used=timedelta(minutes=7), limit=limit)
    line = time_line_of(ChildTalkLayer.parent_summary(None, [], language, talk_time))
    assert "{" not in line  # every placeholder filled
    assert "7" in line
