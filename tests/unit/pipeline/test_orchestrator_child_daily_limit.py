"""Orchestrator child-talk turns at the daily limit (s10b §4.16; owner, 2026-11-13).

What must hold: the daily-limit message and the final answer reach the child only through
safety_out, as a voice note like every reply to a child; a final answer safety_out blocks is
never sent and ends nothing, so the next message ends the session instead. The parent's choice
of limit goes through the journey and safety_out too; a child can't make it.
"""

from datetime import timedelta

import pytest

from app.constants.child_talk_copy import (
    ASK_A_GROWNUP,
    CHILD_DAILY_LIMIT_REACHED,
    CHILD_REFUSE_OTHER,
)
from app.domain.enums import (
    ChildSessionEndReason,
    CuriosityDomain,
    DailyTalkLimit,
    FixedReplyKind,
    Language,
    PartKind,
    Route,
    SafetyCategory,
)
from app.domain.models.child_session import ChildSessionSpan
from app.domain.models.turn import TurnContext
from app.domain.models.writes import ChildSessionEnd, ChildTalkDailyLimit, ChildTalkTurn
from tests.fakes.domain_policy import policy_answer, reply_answer, scripted_policy
from tests.fakes.language_model import FakeLanguageModel
from tests.support.child_talk import (
    CHILD_ANSWER,
    CHILD_REPLY,
    SESSION_ID,
    consented_child,
    open_session,
)
from tests.support.turn_context import NOW, button_reply, text_message, turn_context
from tests.unit.pipeline.test_orchestrator import flagging, run

pytestmark = pytest.mark.unit

MUNNI = consented_child()  # the default 30 minutes
H = Language.HINGLISH


def finished_today(minutes: int) -> list[ChildSessionSpan]:
    """`minutes` of talk today, in sessions of at most 10 minutes (the session cap)."""
    sessions: list[ChildSessionSpan] = []
    for number, start_minute in enumerate(range(0, minutes, 10)):
        started = NOW - timedelta(hours=4) + timedelta(minutes=35 * number)
        length = timedelta(minutes=min(10, minutes - start_minute))
        sessions.append(
            ChildSessionSpan(
                learner_id=MUNNI.id,
                started_at=started,
                ended_at=started + length,
                end_reason=ChildSessionEndReason.CHILD_ENDED,
                last_answered_at=started + length,
                turns_count=4,
            )
        )
    return sessions


def starting(text: str, *, used_minutes: int) -> TurnContext:
    return turn_context(text_message(text), learners=[MUNNI]).model_copy(
        update={"child_talk_today": finished_today(used_minutes)}
    )


def in_session_at_the_limit(text: str = "chaand kyun chamakta hai?") -> TurnContext:
    session = open_session(MUNNI, turns=2, started=NOW - timedelta(minutes=6))
    the_open_one = ChildSessionSpan(
        learner_id=MUNNI.id,
        started_at=session.started_at,
        ended_at=None,
        end_reason=None,
        last_answered_at=session.started_at + timedelta(minutes=3),
        turns_count=2,
    )
    return turn_context(text_message(text), learners=[MUNNI]).model_copy(
        update={
            "child_session": session,
            "child_talk_today": [*finished_today(24), the_open_one],
        }
    )


async def test_a_child_whose_time_is_used_up_hears_the_message_as_a_checked_voice_note() -> None:
    result = await run(
        starting("Main Munni hoon, chaand kyun chamakta hai?", used_minutes=30),
        llm=FakeLanguageModel([CHILD_REPLY]),
    )
    outcome = result.outcome
    assert outcome.route is Route.CHILD_TALK
    assert CHILD_DAILY_LIMIT_REACHED[H] in result.delivered
    assert CHILD_ANSWER not in result.delivered
    assert outcome.writes == []
    assert outcome.delivery.parts[0].kind is PartKind.AUDIO
    assert "assistant" in result.classifier.speakers()  # safety_out saw the reply


async def test_the_answer_that_uses_up_the_day_is_sent_whole_then_the_session_ends() -> None:
    result = await run(in_session_at_the_limit(), llm=FakeLanguageModel([CHILD_REPLY]))
    outcome = result.outcome
    assert outcome.route is Route.CHILD_TALK
    assert CHILD_ANSWER in result.delivered
    assert CHILD_DAILY_LIMIT_REACHED[H] in result.delivered
    assert outcome.writes == [
        ChildTalkTurn(session_id=SESSION_ID, topic=CuriosityDomain.EARTH_SKY),
        ChildSessionEnd(session_id=SESSION_ID, reason=ChildSessionEndReason.DAILY_LIMIT),
    ]
    assert result.classifier.speakers() == ["user", "assistant"]


async def test_a_last_answer_safety_out_blocks_is_never_sent_and_ends_nothing() -> None:
    confirmed = scripted_policy(reply_outputs=[reply_answer(medical=True)])[0]
    result = await run(
        in_session_at_the_limit(),
        classifier=flagging(reply=[SafetyCategory.SPECIALIZED_ADVICE]),
        policy=confirmed,
        llm=FakeLanguageModel([CHILD_REPLY]),
    )
    assert result.outcome.fixed_reply_kind is FixedReplyKind.REFUSE
    assert CHILD_ANSWER not in result.delivered
    assert CHILD_REFUSE_OTHER[H] in result.delivered
    assert result.outcome.writes == []  # the session stays open; the next message ends it


# --- the parent choosing the limit (owner, 2026-11-13) -------------------------------------


async def test_a_parents_limit_button_is_set_through_the_journey_and_checked() -> None:
    button = f"jrn:limit:60_minutes:{MUNNI.id}"
    ctx = turn_context(button_reply(button), learners=[MUNNI])
    result = await run(ctx)
    assert result.outcome.route is Route.JOURNEY
    assert result.outcome.writes == [
        ChildTalkDailyLimit(learner_id=MUNNI.id, limit=DailyTalkLimit.MINUTES_60)
    ]
    assert "1 ghanta" in result.delivered
    assert "assistant" in result.classifier.speakers()  # safety_out saw the reply


async def test_a_parents_typed_no_limit_is_set_through_the_journey() -> None:
    """That the intent model never reads it is tested in the journey layer, with reading on
    (test_child_talk_settings_layer)."""
    ctx = turn_context(text_message("Munni ka limit hata do"), learners=[MUNNI])
    result = await run(ctx)
    assert result.outcome.route is Route.JOURNEY
    assert result.outcome.writes == [
        ChildTalkDailyLimit(learner_id=MUNNI.id, limit=DailyTalkLimit.NO_LIMIT)
    ]
    assert "koi limit nahi" in result.delivered


async def test_the_same_button_from_inside_a_childs_session_changes_nothing() -> None:
    button = f"jrn:limit:no_limit:{MUNNI.id}"
    ctx = turn_context(button_reply(button), learners=[MUNNI]).model_copy(
        update={"child_session": open_session(MUNNI, turns=1)}
    )
    result = await run(ctx, llm=FakeLanguageModel([CHILD_REPLY]))
    assert result.outcome.route is Route.CHILD_TALK
    assert result.outcome.writes == []
    assert ASK_A_GROWNUP[H] in result.delivered


async def test_after_a_crisis_the_parents_note_has_no_time_line() -> None:
    """C15: the crisis note stays the fixed, reviewed text; the time used is for ordinary
    summaries only."""
    result = await run(
        in_session_at_the_limit("mujhe jeena nahi hai, sab mujhe daante hain"),
        classifier=flagging(user=[SafetyCategory.SELF_HARM]),
        llm=FakeLanguageModel([CHILD_REPLY], delay_s=5),
        policy=scripted_policy([policy_answer(self_harm=True)])[0],
    )
    assert result.outcome.route is Route.CRISIS
    assert "Mummy-Papa ke liye" in result.delivered
    assert "⏱️" not in result.delivered


async def test_an_ordinary_goodbye_carries_the_time_line_through_safety_out() -> None:
    result = await run(in_session_at_the_limit("bye"), llm=FakeLanguageModel([CHILD_REPLY]))
    assert "⏱️ Talk today: 30 minutes in all" in result.delivered  # "bye": an English reply
    assert "assistant" in result.classifier.speakers()


async def test_a_parent_asking_the_time_left_gets_it_through_the_journey_and_checked() -> None:
    ctx = turn_context(text_message("Munni ka aaj Marg se kitna time bacha hai?"), learners=[MUNNI])
    ctx = ctx.model_copy(update={"child_talk_today": finished_today(14)})
    result = await run(ctx)
    assert result.outcome.route is Route.JOURNEY
    assert result.outcome.writes == []
    assert "⏱️ Aaj Munni ne Marg se 14 minute baat ki." in result.delivered
    assert "16 minute aur baaki hain" in result.delivered
    assert "assistant" in result.classifier.speakers()  # safety_out saw the reply
