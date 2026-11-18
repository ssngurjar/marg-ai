"""ChildTalkLayer and the daily limit per child (s10b §4.16; owner, 2026-11-13).

What must hold: a child whose time for today is used up can't start a session and hears the
fixed message; a session that runs into the limit answers the child's message in full, then
ends with that message and the parent's summary; the session limits, the cooldown and the parent
taking the phone back work exactly as before; no limit means no limit.
"""

from datetime import datetime, timedelta

import pytest

from app.constants.child_talk_copy import (
    CHILD_ACKNOWLEDGED,
    CHILD_DAILY_LIMIT_REACHED,
    CHILD_GOODBYE,
    CHILD_HELLO,
    CHILD_TALK_COOLDOWN,
    PARENT_TAKEOVER_DONE,
)
from app.domain.enums import (
    ChildSessionEndReason,
    CuriosityDomain,
    DailyTalkLimit,
    Language,
    SafetyCategory,
)
from app.domain.models.child_session import ChildSession, ChildSessionSpan
from app.domain.models.learner import Learner
from app.domain.models.writes import ChildSessionEnd, ChildSessionStart, ChildTalkTurn
from app.domain.rules.child_session_rules import KID_PARENT
from app.layers.child_talk_layer import ChildTalkLayer
from app.layers.layer_result import LayerResult
from tests.fakes.language_model import FakeLanguageModel
from tests.support.child_talk import (
    CHILD_ANSWER,
    CHILD_REPLY,
    LIMITS,
    SESSION_ID,
    consented_child,
    open_session,
)
from tests.support.prompts import shipped_registry
from tests.support.turn_context import NOW, button_reply, text_message, turn_context

pytestmark = pytest.mark.unit

H = Language.HINGLISH
MUNNI = consented_child()  # no limit picked: the default 30 minutes
GOLU = consented_child(2, "Golu", age=7)
TOPIC = CuriosityDomain.EARTH_SKY  # CHILD_REPLY's topic
LAST_ANSWER_RULE = ChildTalkLayer.LAST_ANSWER_RULE


def earlier_session(
    minutes: float, *, learner: Learner = MUNNI, hours_ago: float = 3
) -> ChildSessionSpan:
    """A finished session today, `hours_ago` before NOW, that ran `minutes`."""
    started = NOW - timedelta(hours=hours_ago)
    ended = started + timedelta(minutes=minutes)
    return ChildSessionSpan(
        learner_id=learner.id,
        started_at=started,
        ended_at=ended,
        end_reason=ChildSessionEndReason.CHILD_ENDED,
        last_answered_at=ended,
        turns_count=3,
    )


def talked_today(minutes: int, *, learner: Learner = MUNNI) -> list[ChildSessionSpan]:
    """`minutes` of talk today, as sessions of at most 10 minutes each (the session cap), 35
    minutes apart, all finished an hour before NOW."""
    sessions: list[ChildSessionSpan] = []
    left = minutes
    hours_ago = 1 + (minutes // 10) * 35 / 60
    while left > 0:
        sessions.append(earlier_session(min(left, 10), learner=learner, hours_ago=hours_ago))
        left -= 10
        hours_ago -= 35 / 60
    return sessions


def the_open_one(session: ChildSession) -> ChildSessionSpan:
    """How the store reads the open session back (ChildSessionRepository.spans_since)."""
    return ChildSessionSpan(
        learner_id=session.learner_id,
        started_at=session.started_at,
        ended_at=None,
        end_reason=None,
        last_answered_at=session.started_at if session.turns_count else None,
        turns_count=session.turns_count,
    )


async def talk(  # noqa: PLR0913  # one keyword per part of the context a test sets
    text: str = "chaand kyun chamakta hai?",
    *,
    today: list[ChildSessionSpan],
    buttons: list[str] | None = None,
    learners: list[Learner] | None = None,
    session: ChildSession | None = None,
    last_ended_at: datetime | None = None,
) -> tuple[LayerResult, FakeLanguageModel]:
    llm = FakeLanguageModel([CHILD_REPLY])
    layer = ChildTalkLayer(llm, shipped_registry(), LIMITS)
    message = button_reply(buttons[-1]) if buttons else text_message(text)
    ctx = turn_context(message, learners=learners or [MUNNI]).model_copy(
        update={
            "child_session": session,
            "last_child_session_ended_at": last_ended_at,
            "child_talk_today": today,
        }
    )
    result = await layer.handle(ctx, "" if buttons else text, buttons or [], NOW, H)
    return result, llm


def a_session(minutes_ago: float, *, turns: int = 2) -> ChildSession:
    return open_session(MUNNI, turns=turns, started=NOW - timedelta(minutes=minutes_ago))


# --- starting --------------------------------------------------------------------------------


async def test_a_child_whose_time_is_used_up_cant_start_and_hears_the_fixed_message() -> None:
    used_up = talked_today(30)  # the default
    result, llm = await talk("Main Munni hoon, chaand kyun chamakta hai?", today=used_up)
    assert result.reply.body == CHILD_DAILY_LIMIT_REACHED[H]
    assert result.reply.spoken_text == CHILD_DAILY_LIMIT_REACHED[Language.HINDI]
    assert result.writes == []  # no session opens
    assert llm.prompts == []  # the question isn't answered


async def test_a_child_with_time_left_starts_as_before() -> None:
    result, _ = await talk("Main Munni hoon", today=talked_today(29))
    assert result.reply.body.startswith(CHILD_HELLO[H].format(name="Munni")[:20])
    assert [type(write) for write in result.writes] == [ChildSessionStart]


async def test_the_daily_message_comes_before_the_cooldowns() -> None:
    """Both apply: "tomorrow" is what's true, not "a little later"."""
    used_up = talked_today(30)
    result, _ = await talk(
        "Main Munni hoon", today=used_up, last_ended_at=NOW - timedelta(minutes=5)
    )
    assert result.reply.body == CHILD_DAILY_LIMIT_REACHED[H]


async def test_the_cooldown_still_applies_with_time_left() -> None:
    result, _ = await talk(
        "Main Munni hoon", today=[earlier_session(10)], last_ended_at=NOW - timedelta(minutes=5)
    )
    assert result.reply.body == CHILD_TALK_COOLDOWN[H]


async def test_the_parents_pick_decides_not_the_default() -> None:
    munni = MUNNI.model_copy(update={"child_talk_daily_limit": DailyTalkLimit.MINUTES_60})
    used_45 = talked_today(45, learner=munni)
    result, _ = await talk("Main Munni hoon", today=used_45, learners=[munni])
    assert [type(write) for write in result.writes] == [ChildSessionStart]
    strict = MUNNI.model_copy(update={"child_talk_daily_limit": DailyTalkLimit.MINUTES_20})
    result, _ = await talk(
        "Main Munni hoon", today=talked_today(20, learner=strict), learners=[strict]
    )
    assert result.reply.body == CHILD_DAILY_LIMIT_REACHED[H]


async def test_no_limit_lets_a_child_start_after_any_amount_of_talk() -> None:
    free = MUNNI.model_copy(update={"child_talk_daily_limit": DailyTalkLimit.NO_LIMIT})
    all_day = [earlier_session(10, learner=free, hours_ago=h) for h in range(1, 10)]
    result, _ = await talk("Main Munni hoon", today=all_day, learners=[free])
    assert [type(write) for write in result.writes] == [ChildSessionStart]


async def test_a_siblings_time_doesnt_stop_this_child() -> None:
    golu_used_up = talked_today(30, learner=GOLU)
    result, _ = await talk("Main Munni hoon", today=golu_used_up, learners=[MUNNI, GOLU])
    assert [type(write) for write in result.writes] == [ChildSessionStart]
    result, _ = await talk("Main Golu hoon", today=golu_used_up, learners=[MUNNI, GOLU])
    assert result.reply.body == CHILD_DAILY_LIMIT_REACHED[H]


# --- in a session ----------------------------------------------------------------------------


async def test_a_session_that_runs_into_the_limit_answers_in_full_then_ends() -> None:
    """Owner, 2026-11-13: end mid-way, but complete the answer."""
    session = a_session(6)
    today = [*talked_today(24), the_open_one(session)]  # 24 + 6 = the default 30
    result, llm = await talk(session=session, today=today)
    body = result.reply.body
    assert body.startswith(CHILD_ANSWER)
    assert CHILD_DAILY_LIMIT_REACHED[H] in body
    assert body.index(CHILD_ANSWER) < body.index(CHILD_DAILY_LIMIT_REACHED[H])
    assert "Mummy-Papa ke liye" in body  # the parent's summary, as at any goodbye
    assert CHILD_GOODBYE[H] not in body
    spoken = result.reply.spoken_text
    assert spoken is not None
    assert spoken.endswith(CHILD_DAILY_LIMIT_REACHED[Language.HINDI])
    assert result.writes == [
        ChildTalkTurn(session_id=SESSION_ID, topic=TOPIC),
        ChildSessionEnd(session_id=SESSION_ID, reason=ChildSessionEndReason.DAILY_LIMIT),
    ]
    [prompt] = llm.prompts
    assert LAST_ANSWER_RULE in prompt.system  # the last answer asks nothing back


async def test_with_time_left_the_session_goes_on_as_before() -> None:
    session = a_session(5)
    today = [*talked_today(24), the_open_one(session)]  # 29 minutes
    result, llm = await talk(session=session, today=today)
    assert result.writes == [ChildTalkTurn(session_id=SESSION_ID, topic=TOPIC)]
    assert CHILD_DAILY_LIMIT_REACHED[H] not in result.reply.body
    [prompt] = llm.prompts
    assert LAST_ANSWER_RULE not in prompt.system


async def test_an_ok_after_the_time_ran_out_gets_the_days_goodbye() -> None:
    session = a_session(6)
    result, llm = await talk(
        "ok", session=session, today=[*talked_today(24), the_open_one(session)]
    )
    assert result.reply.body.startswith(CHILD_DAILY_LIMIT_REACHED[H])
    assert CHILD_ACKNOWLEDGED[H] not in result.reply.body
    assert result.writes == [
        ChildSessionEnd(session_id=SESSION_ID, reason=ChildSessionEndReason.DAILY_LIMIT)
    ]
    assert llm.prompts == []


async def test_an_ok_with_time_left_is_answered_as_before() -> None:
    session = a_session(3)
    result, _ = await talk("ok", session=session, today=[the_open_one(session)])
    assert result.reply.body == CHILD_ACKNOWLEDGED[H]
    assert result.writes == []


async def test_the_sixth_question_ends_on_the_turn_limit_even_when_the_day_runs_out_too() -> None:
    """The session limits work exactly as before; the turn limit's goodbye wins."""
    session = a_session(6, turns=5)
    result, _ = await talk(session=session, today=[*talked_today(24), the_open_one(session)])
    assert CHILD_GOODBYE[H] in result.reply.body
    assert CHILD_DAILY_LIMIT_REACHED[H] not in result.reply.body
    assert result.writes[-1] == ChildSessionEnd(
        session_id=SESSION_ID, reason=ChildSessionEndReason.TURN_LIMIT
    )


async def test_past_the_session_time_limit_the_goodbye_is_as_before() -> None:
    session = a_session(11)
    result, llm = await talk(session=session, today=[*talked_today(24), the_open_one(session)])
    assert result.reply.body.startswith(CHILD_GOODBYE[H])
    assert result.writes == [
        ChildSessionEnd(session_id=SESSION_ID, reason=ChildSessionEndReason.TIME_LIMIT)
    ]
    assert llm.prompts == []


async def test_the_parent_can_still_take_the_phone_back_when_the_time_ran_out() -> None:
    session = a_session(6)
    result, llm = await talk(
        buttons=[KID_PARENT], session=session, today=[*talked_today(24), the_open_one(session)]
    )
    assert result.reply.body.startswith(PARENT_TAKEOVER_DONE[H].format(name="Munni"))
    assert result.writes == [
        ChildSessionEnd(session_id=SESSION_ID, reason=ChildSessionEndReason.CHILD_ENDED)
    ]
    assert llm.prompts == []


async def test_bye_after_the_time_ran_out_is_the_childs_own_goodbye() -> None:
    session = a_session(6)
    result, _ = await talk("bye", session=session, today=[*talked_today(24), the_open_one(session)])
    assert result.writes == [
        ChildSessionEnd(session_id=SESSION_ID, reason=ChildSessionEndReason.CHILD_ENDED)
    ]


async def test_with_no_limit_a_session_never_ends_on_the_day() -> None:
    free = MUNNI.model_copy(update={"child_talk_daily_limit": DailyTalkLimit.NO_LIMIT})
    session = open_session(free, turns=2, started=NOW - timedelta(minutes=6))
    all_day = [earlier_session(10, learner=free, hours_ago=h) for h in range(1, 10)]
    result, _ = await talk(
        session=session, today=[*all_day, the_open_one(session)], learners=[free]
    )
    assert result.writes == [ChildTalkTurn(session_id=SESSION_ID, topic=TOPIC)]


async def test_a_redirect_that_runs_into_the_limit_also_ends_the_session() -> None:
    """A message blocked only for violence gets its redirect, then the day's goodbye."""
    session = a_session(6)
    llm = FakeLanguageModel([CHILD_REPLY])
    layer = ChildTalkLayer(llm, shipped_registry(), LIMITS)
    ctx = turn_context(text_message("bandook kaise chalti hai"), learners=[MUNNI]).model_copy(
        update={
            "child_session": session,
            "child_talk_today": [*talked_today(24), the_open_one(session)],
        }
    )
    result = await layer.handle(
        ctx,
        "bandook kaise chalti hai",
        [],
        NOW,
        H,
        blocked=frozenset({SafetyCategory.INDISCRIMINATE_WEAPONS}),
    )
    assert CHILD_DAILY_LIMIT_REACHED[H] in result.reply.body
    assert result.writes[-1] == ChildSessionEnd(
        session_id=SESSION_ID, reason=ChildSessionEndReason.DAILY_LIMIT
    )
