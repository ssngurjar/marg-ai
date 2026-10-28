"""Orchestrator child-talk turns (s10b §4.16, C13; s07 C15): the child is the speaker.

What must hold: every reply to a child passed safety_out with the child rules; a crisis gets the
child-worded helpline text and ends the session; after an abuse disclosure the parent is told
nothing; the parent is never shown the child's words.
"""

import pytest

from app.constants.child_talk_copy import (
    CHILD_FALLBACK,
    CHILD_REFUSE_DANGER,
    CHILD_REFUSE_OTHER,
)
from app.core.errors import ProviderResponseInvalid, ProviderUnavailable
from app.domain.enums import (
    ChildSessionEndReason,
    CuriosityDomain,
    FixedReplyKind,
    Language,
    PartKind,
    Route,
    SafetyCategory,
)
from app.domain.models.turn import TurnContext
from app.domain.models.writes import ChildSessionEnd, ChildTalkTurn
from app.layers.onboarding_layer import OnboardingLayer
from app.pipeline.null_turn_observer import NullTurnObserver
from app.pipeline.orchestrator import Orchestrator, PipelineSteps
from app.safety.safety_gate import SafetyGate
from tests.fakes.clock import FixedClock
from tests.fakes.domain_policy import policy_answer, reply_answer, scripted_policy
from tests.fakes.language_model import FakeLanguageModel
from tests.fakes.safety_classifier import FakeSafetyClassifier
from tests.fakes.step_recorder import MemoryStepRecorder
from tests.fakes.voice import FakeVoice
from tests.support.child_talk import (
    CHILD_ANSWER,
    CHILD_REPLY,
    SESSION_ID,
    consented_child,
    open_session,
)
from tests.support.prompts import shipped_registry
from tests.support.turn_context import NOW, button_reply, text_message, turn_context
from tests.unit.pipeline.test_orchestrator import INVITE_LINK, SETTINGS, flagging, journey_for, run

pytestmark = pytest.mark.unit

MUNNI = consented_child()
CHILD_REPLY_TOPIC = CuriosityDomain.EARTH_SKY  # CHILD_REPLY's topic
SAID = "aaj school mein kisi ne mujhe bahut maara, mujhe dar lagta hai"


def in_session(text: str = "chaand kyun chamakta hai?") -> TurnContext:
    return turn_context(text_message(text), learners=[MUNNI]).model_copy(
        update={"child_session": open_session(MUNNI)}
    )


async def test_a_childs_typed_question_is_answered_with_a_voice_note_too() -> None:
    result = await run(in_session(), llm=FakeLanguageModel([CHILD_REPLY]))
    outcome = result.outcome
    assert outcome.route is Route.CHILD_TALK
    assert CHILD_ANSWER in result.delivered
    assert outcome.delivery.parts[0].kind is PartKind.AUDIO
    assert result.voice.synthesizer.requests
    assert outcome.writes == [ChildTalkTurn(session_id=SESSION_ID, topic=CHILD_REPLY_TOPIC)]
    assert result.classifier.speakers() == ["user", "assistant"]


async def test_a_child_in_distress_gets_child_words_and_the_parent_a_gentle_note() -> None:
    result = await run(
        in_session("mujhe jeena nahi hai, sab mujhe daante hain"),
        classifier=flagging(user=[SafetyCategory.SELF_HARM]),
        llm=FakeLanguageModel([CHILD_REPLY], delay_s=5),
        policy=scripted_policy([policy_answer(self_harm=True)])[0],  # S11 confirmed
    )
    outcome = result.outcome
    assert outcome.route is Route.CRISIS
    assert outcome.fixed_reply_kind is FixedReplyKind.CRISIS
    assert "Yeh tumhari galti nahi hai" in result.delivered
    assert "1098" in result.delivered
    assert "Mummy-Papa ke liye" in result.delivered
    assert "14416" in result.delivered
    for word in ("jeena", "daante"):
        assert word not in result.delivered  # the parent never sees the child's words
    assert outcome.writes == [
        ChildSessionEnd(session_id=SESSION_ID, reason=ChildSessionEndReason.CRISIS)
    ]
    [spoken] = result.voice.synthesizer.requests
    assert "14416" not in spoken.text  # the parent's note is written, never spoken


async def test_after_an_abuse_disclosure_the_parent_is_told_nothing() -> None:
    result = await run(
        in_session(SAID),
        classifier=flagging(user=[SafetyCategory.ABUSE_DISCLOSURE]),
        llm=FakeLanguageModel([CHILD_REPLY], delay_s=5),
    )
    assert result.outcome.fixed_reply_kind is FixedReplyKind.CRISIS
    assert "1098" in result.delivered
    assert "Mummy-Papa ke liye" not in result.delivered
    assert "maara" not in result.delivered
    assert result.outcome.writes == [
        ChildSessionEnd(session_id=SESSION_ID, reason=ChildSessionEndReason.CRISIS)
    ]


REDIRECT_ANSWER = "Bandook se chot lagti hai. Isliye bade hi sambhalte hain."
REDIRECT_REPLY: dict[str, object] = {
    "confident": True,
    "answer": REDIRECT_ANSWER,
    "find_out": "Taali bajao aur aawaz suno.",
    "ask_back": "Aawaz kitni door jaati hai?",
    "who_explores_this": "",
    "topic": "art_music",
    "spoken_text": "बंदूक से चोट लगती है। इसलिए बड़े ही संभालते हैं। ताली बजाओ और आवाज़ सुनो।",
}


async def test_a_curious_question_about_weapons_gets_a_redirect_not_a_flat_refusal() -> None:
    """Owner, 2026-10-28: a blocked child message gets what a kind elder would say: why, and
    something safe to wonder about. The blocked answer itself is never used."""
    llm = FakeLanguageModel([REDIRECT_REPLY])
    result = await run(
        in_session("bandook kaise chalate hain?"),
        classifier=flagging(user=[SafetyCategory.INDISCRIMINATE_WEAPONS]),
        llm=llm,
    )
    assert result.outcome.route is Route.CHILD_TALK
    assert result.outcome.fixed_reply_kind is None
    assert REDIRECT_ANSWER in result.delivered
    assert llm.prompts[-1].prompt_id == "child_redirect"
    assert result.classifier.speakers() == ["user", "assistant"]  # sealed by safety_out
    assert result.outcome.writes == [ChildTalkTurn(session_id=SESSION_ID, topic=None)] or (
        result.outcome.writes
        == [ChildTalkTurn(session_id=SESSION_ID, topic=CuriosityDomain.ART_MUSIC)]
    )


@pytest.mark.parametrize(
    ("category", "fixed"),
    [
        (SafetyCategory.SEXUAL_CONTENT, CHILD_REFUSE_OTHER),
        (SafetyCategory.PRIVACY, CHILD_REFUSE_OTHER),
    ],
)
async def test_other_blocked_messages_keep_the_fixed_child_refusal(
    category: SafetyCategory, fixed: dict[Language, str]
) -> None:
    llm = FakeLanguageModel([CHILD_REPLY], delay_s=5)
    result = await run(in_session("kuch bhi"), classifier=flagging(user=[category]), llm=llm)
    assert result.outcome.fixed_reply_kind is FixedReplyKind.REFUSE
    assert fixed[Language.HINGLISH] in result.delivered
    assert all(prompt.prompt_id != "child_redirect" for prompt in llm.prompts)
    assert result.outcome.writes == []


async def test_weapons_with_sexual_content_keeps_the_fixed_refusal() -> None:
    """A redirect only when every flagged category allows one."""
    result = await run(
        in_session("kuch bhi"),
        classifier=flagging(
            user=[SafetyCategory.INDISCRIMINATE_WEAPONS, SafetyCategory.SEXUAL_CONTENT]
        ),
        llm=FakeLanguageModel([CHILD_REPLY], delay_s=5),
    )
    assert result.outcome.fixed_reply_kind is FixedReplyKind.REFUSE


async def test_a_redirect_the_model_cant_write_falls_back_to_the_fixed_refusal() -> None:
    down = ProviderUnavailable("down", provider="meta_model_api")
    result = await run(
        in_session("bandook kaise chalate hain?"),
        classifier=flagging(user=[SafetyCategory.INDISCRIMINATE_WEAPONS]),
        llm=FakeLanguageModel([down]),
    )
    assert result.outcome.fixed_reply_kind is FixedReplyKind.REFUSE
    assert CHILD_REFUSE_DANGER[Language.HINGLISH] in result.delivered
    assert "child_redirect" in [step.detail for step in result.recorder.steps]


async def test_a_redirect_that_fails_its_checks_twice_sends_the_fixed_text_for_its_reason() -> None:
    gave_up = ProviderResponseInvalid("after repair", provider="meta_model_api", retryable=False)
    result = await run(
        in_session("bandook kaise chalate hain?"),
        classifier=flagging(user=[SafetyCategory.INDISCRIMINATE_WEAPONS]),
        llm=FakeLanguageModel([gave_up]),
    )
    assert CHILD_REFUSE_DANGER[Language.HINGLISH] in result.delivered
    assert REDIRECT_ANSWER not in result.delivered


async def test_a_reply_that_fails_its_child_checks_twice_is_never_sent() -> None:
    """The model's reply kept asking the child's school (the repair didn't fix it): the adapter
    gives up, the redirect gives up too, and the child gets the kind fixed reply instead."""
    gave_up = ProviderResponseInvalid("after repair", provider="meta_model_api", retryable=False)
    result = await run(in_session(), llm=FakeLanguageModel([gave_up]))
    assert CHILD_FALLBACK[Language.HINGLISH] in result.delivered
    assert result.outcome.writes == [ChildTalkTurn(session_id=SESSION_ID, topic=None)]


async def test_a_reply_the_guard_flags_is_replaced_by_the_child_refusal() -> None:
    confirmed = scripted_policy(reply_outputs=[reply_answer(medical=True)])[0]
    result = await run(
        in_session(),
        classifier=flagging(reply=[SafetyCategory.SPECIALIZED_ADVICE]),
        policy=confirmed,
        llm=FakeLanguageModel([CHILD_REPLY]),
    )
    assert result.outcome.fixed_reply_kind is FixedReplyKind.REFUSE
    assert result.outcome.route is Route.CHILD_TALK
    assert CHILD_ANSWER not in result.delivered
    assert CHILD_REFUSE_OTHER[Language.HINGLISH] in result.delivered  # our reply: GENERIC


async def test_with_child_talk_switched_off_the_button_goes_to_the_journey() -> None:
    llm = FakeLanguageModel([CHILD_REPLY])
    orchestrator = Orchestrator(
        PipelineSteps(
            gate=SafetyGate(FakeSafetyClassifier(), scripted_policy()[0]),
            journey=journey_for(llm),
            onboarding=OnboardingLayer(llm, shipped_registry(), invite_link=INVITE_LINK),
            voice=FakeVoice().steps(),
            child_talk=None,
            clock=FixedClock(NOW),
        ),
        SETTINGS,
    )
    ctx = turn_context(button_reply("kid:start"), learners=[MUNNI])
    outcome = await orchestrator.run_turn(ctx, MemoryStepRecorder(), NullTurnObserver())
    assert outcome.route is Route.REPEAT_PLEASE
    assert outcome.writes == []
    assert llm.prompts == []
