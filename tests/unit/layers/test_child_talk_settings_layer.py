"""The parent choosing each child's daily talk limit (s10b §4.16; owner, 2026-11-13): 20
minutes, 30 minutes or 1 hour on buttons, any of them or no limit typed; asked right after the
yes to child talk, and changed any time by writing "limit". Only for the parent's own child who
may talk; nothing is ever set from a button or words it can't read."""

from datetime import timedelta
from uuid import UUID

import pytest

from app.constants.child_talk_copy import (
    ASK_A_GROWNUP,
    CHILD_TALK_LIMIT_WHICH_CHILD,
    DAILY_LIMIT_NAMES,
)
from app.constants.journey_copy import KHOJ_BUTTONS, KHOJ_DONE, TODAY_KHOJ_BUTTON
from app.constants.onboarding_copy import COPY
from app.domain.enums import (
    ChildSessionEndReason,
    ConversationState,
    CopyKey,
    DailyTalkLimit,
    Language,
    Role,
)
from app.domain.models.child_session import ChildSessionSpan
from app.domain.models.learner import Learner
from app.domain.models.writes import ChildTalkConsent, ChildTalkDailyLimit
from app.layers.child_talk_layer import ChildTalkLayer
from app.layers.child_talk_settings_layer import ChildTalkSettingsLayer, ParentTurnFacts
from app.layers.journey_layer import ParentMessage
from app.layers.layer_result import LayerResult
from tests.fakes.language_model import FakeLanguageModel, PromptRoutedLanguageModel
from tests.support.child_talk import CHILD_REPLY, LIMITS, consented_child, open_session
from tests.support.journey import child, first_choice, offer
from tests.support.prompts import shipped_registry
from tests.support.turn_context import NOW, button_reply, text_message, turn_context
from tests.unit.layers.test_journey_layer import layer_with, reading
from tests.unit.layers.test_onboarding_layer import at, handle

pytestmark = pytest.mark.unit

H = Language.HINGLISH
MUNNI = consented_child(1, "Munni")
GOLU = consented_child(2, "Golu", age=7)
NOT_ALLOWED = child(4, "Chotu", age=6)  # the parent hasn't said yes to child talk
TEEN = child(5, "Rani", age=14)


def limit_button(limit: DailyTalkLimit | str, learner: Learner) -> str:
    value = limit.value if isinstance(limit, DailyTalkLimit) else limit
    return f"jrn:limit:{value}:{learner.id}"


def settle(  # noqa: PLR0913  # one keyword per part of the turn a test sets
    *,
    text: str = "",
    button: str | None = None,
    learners: list[Learner] | None = None,
    today: list[ChildSessionSpan] | None = None,
    khoj_open: bool = False,
    register: Language = H,
) -> LayerResult | None:
    facts = ParentTurnFacts(
        learners=learners if learners is not None else [MUNNI],
        child_talk_today=today or [],
        now=NOW,
        limits=LIMITS,
        khoj_open=khoj_open,
    )
    return ChildTalkSettingsLayer.daily_limit(facts, button, text, register)


def limit_set(result: LayerResult | None) -> ChildTalkDailyLimit:
    assert result is not None
    [write] = result.writes
    assert isinstance(write, ChildTalkDailyLimit)
    return write


def reply_of(result: LayerResult | None) -> str:
    assert result is not None
    return result.reply.body


# --- buttons ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("limit", "said"),
    [
        (DailyTalkLimit.MINUTES_20, "20 minute"),
        (DailyTalkLimit.MINUTES_30, "30 minute"),
        (DailyTalkLimit.MINUTES_60, "1 ghanta"),
    ],
)
def test_each_button_sets_that_limit_for_that_child(limit: DailyTalkLimit, said: str) -> None:
    result = settle(button=limit_button(limit, MUNNI))
    assert limit_set(result) == ChildTalkDailyLimit(learner_id=MUNNI.id, limit=limit)
    assert reply_of(result).startswith(f"Theek hai! Ab Munni roz {said} tak")
    assert 'likhiye "limit badlo"' in reply_of(result)  # how to change it later


def test_after_setting_it_todays_khoj_is_offered() -> None:
    result = settle(button=limit_button(DailyTalkLimit.MINUTES_20, MUNNI))
    assert result is not None
    assert result.reply.buttons == [TODAY_KHOJ_BUTTON[H]]


def test_with_a_khoj_open_its_buttons_stay() -> None:
    result = settle(button=limit_button(DailyTalkLimit.MINUTES_20, MUNNI), khoj_open=True)
    assert result is not None
    assert tuple(result.reply.buttons) == KHOJ_BUTTONS[H]


def test_the_ask_button_shows_that_childs_limit_question() -> None:
    result = settle(button=limit_button("ask", GOLU), learners=[MUNNI, GOLU])
    assert result is not None
    assert result.writes == []
    assert reply_of(result).startswith("Golu roz kitni der")
    assert [button.id for button in result.reply.buttons] == [
        limit_button(DailyTalkLimit.MINUTES_20, GOLU),
        limit_button(DailyTalkLimit.MINUTES_30, GOLU),
        limit_button(DailyTalkLimit.MINUTES_60, GOLU),
    ]


@pytest.mark.parametrize(
    "button",
    [
        f"jrn:limit:20_minutes:{UUID(int=99)}",  # another account's child
        "jrn:limit:20_minutes",  # no child
        "jrn:limit:",
        "jrn:limit:20_minutes:not-a-uuid",
        f"jrn:limit:20_minutes:{MUNNI.id}:extra",
    ],
)
def test_a_button_that_doesnt_name_the_parents_own_child_sets_nothing(button: str) -> None:
    """With one child who can talk, the parent is asked again for that child."""
    result = settle(button=button)
    assert result is not None
    assert result.writes == []
    assert reply_of(result).startswith("Munni roz kitni der")


@pytest.mark.parametrize("value", ["45_minutes", "10_minutes", "NO_LIMIT", "", "ask "])
def test_a_button_with_a_limit_that_isnt_a_choice_sets_nothing(value: str) -> None:
    result = settle(button=limit_button(value, MUNNI))
    assert result is not None
    assert result.writes == []
    assert reply_of(result).startswith("Munni roz kitni der")


@pytest.mark.parametrize("button", ["jrn:today", "jrn:done", "nudge:8", "jrn:limitless"])
def test_other_buttons_are_not_about_the_limit(button: str) -> None:
    assert settle(button=button) is None


# --- typed -----------------------------------------------------------------------------------


def test_no_limit_is_set_by_typing_and_the_reply_says_the_session_limits_still_hold() -> None:
    result = settle(text="Munni ka limit hata do")
    assert limit_set(result).limit is DailyTalkLimit.NO_LIMIT
    body = reply_of(result)
    assert body.startswith("Theek hai, Munni ke liye roz ki koi limit nahi.")
    assert "10 minute" in body
    assert "aadha ghanta" in body


@pytest.mark.parametrize(
    ("text", "limit"),
    [
        ("limit 1 ghanta kar do", DailyTalkLimit.MINUTES_60),
        ("munni ki limit 20 minute", DailyTalkLimit.MINUTES_20),
        ("limit aadha ghanta", DailyTalkLimit.MINUTES_30),
    ],
)
def test_a_choice_can_be_typed_too(text: str, limit: DailyTalkLimit) -> None:
    assert limit_set(settle(text=text)).limit is limit


@pytest.mark.parametrize(
    ("language", "text", "start"),
    [
        (Language.HINDI, "लिमिट हटा दो", "ठीक है, Munni के लिए रोज़ की कोई लिमिट नहीं।"),
        (Language.ENGLISH, "no limit", "Done, no daily limit for Munni."),
    ],
)
def test_the_reply_is_in_the_parents_language(language: Language, text: str, start: str) -> None:
    result = settle(text=text, register=language)
    assert limit_set(result).limit is DailyTalkLimit.NO_LIMIT
    assert reply_of(result).startswith(start)


@pytest.mark.parametrize(
    ("stored", "shown"),
    [
        (None, "Abhi: 30 minute."),  # the default
        (DailyTalkLimit.MINUTES_60, "Abhi: 1 ghanta."),
        (DailyTalkLimit.NO_LIMIT, "Abhi: koi limit nahi."),
    ],
)
def test_asking_about_the_limit_shows_the_childs_limit_now_and_the_choices(
    stored: DailyTalkLimit | None, shown: str
) -> None:
    munni = MUNNI.model_copy(update={"child_talk_daily_limit": stored})
    result = settle(text="Munni ki limit kitni hai?", learners=[munni])
    assert result is not None
    assert result.writes == []
    assert shown in reply_of(result)
    assert 'likhiye: "limit hata do"' in reply_of(result)
    assert [button.title for button in result.reply.buttons] == [
        "20 minute",
        "30 minute",
        "1 ghanta",
    ]


@pytest.mark.parametrize(
    "text", ["limit 45 minute kar do", "limit 2 ghante", "limit 20 minute se 30 minute"]
)
def test_a_typed_time_that_isnt_one_clear_choice_is_asked_again_not_guessed(text: str) -> None:
    result = settle(text=text)
    assert result is not None
    assert result.writes == []
    assert reply_of(result).startswith("Munni roz kitni der")


@pytest.mark.parametrize("text", ["Munni ko 1 ghanta baat karne do", "hello", "", "kya haal hai"])
def test_a_message_that_doesnt_say_limit_is_left_alone(text: str) -> None:
    assert settle(text=text) is None


@pytest.mark.parametrize(
    "text",
    [
        "Munni ki TV limit 1 ghanta theek hai?",
        "Munni ka mobile limit hata do",
        "NMMS ki age limit kya hai",
        "kya bachchon ke liye koi limit honi chahiye?",
        "limit se zyada mat khilao",
    ],
)
def test_a_limit_that_isnt_margs_is_left_alone(text: str) -> None:
    """Owner, 2026-11-13: not everything that says "limit" is about Marg's."""
    assert settle(text=text) is None


@pytest.mark.parametrize(
    "text",
    [
        "kya 1 ghanta ki limit theek hai?",
        "Munni ki limit hata do?",
        "should the limit be 30 minutes",
    ],
)
def test_a_question_with_a_value_shows_the_limit_and_sets_nothing(text: str) -> None:
    result = settle(text=text)
    assert result is not None
    assert result.writes == []
    assert reply_of(result).startswith("Munni roz kitni der")
    assert len(result.reply.buttons) == 3


@pytest.mark.parametrize(
    "text", ["Marg se baat karne ki limit kya hai", "Munni ki limit kitni hai?", "limit badlo"]
)
def test_asking_about_margs_limit_without_a_value_shows_it(text: str) -> None:
    result = settle(text=text)
    assert result is not None
    assert result.writes == []
    assert "Abhi: 30 minute." in reply_of(result)


# --- which child -----------------------------------------------------------------------------


def test_with_two_children_who_can_talk_it_asks_which_and_keeps_the_limit_asked_for() -> None:
    result = settle(text="limit hata do", learners=[MUNNI, GOLU])
    assert result is not None
    assert result.writes == []
    assert reply_of(result) == CHILD_TALK_LIMIT_WHICH_CHILD[H]
    assert [(button.id, button.title) for button in result.reply.buttons] == [
        (limit_button(DailyTalkLimit.NO_LIMIT, MUNNI), "Munni"),
        (limit_button(DailyTalkLimit.NO_LIMIT, GOLU), "Golu"),
    ]


def test_with_two_children_and_no_limit_named_the_child_buttons_ask() -> None:
    result = settle(text="limit badlo", learners=[MUNNI, GOLU])
    assert result is not None
    assert [button.id for button in result.reply.buttons] == [
        limit_button("ask", MUNNI),
        limit_button("ask", GOLU),
    ]


def test_a_child_without_a_name_is_shown_by_age_on_the_button() -> None:
    nameless = consented_child(3, None, age=6)
    result = settle(text="limit badlo", learners=[MUNNI, nameless])
    assert result is not None
    assert result.reply.buttons[1].title == "6 saal ka bachcha"


def test_naming_the_child_picks_them_among_several() -> None:
    result = settle(text="Golu ki limit 1 ghanta", learners=[MUNNI, GOLU])
    assert limit_set(result) == ChildTalkDailyLimit(
        learner_id=GOLU.id, limit=DailyTalkLimit.MINUTES_60
    )


def test_only_children_who_may_talk_are_offered() -> None:
    result = settle(text="limit hata do", learners=[MUNNI, NOT_ALLOWED])
    assert limit_set(result).learner_id == MUNNI.id


# --- consent first ---------------------------------------------------------------------------


def test_a_limit_for_a_child_who_may_not_talk_yet_asks_the_consent_question_first() -> None:
    result = settle(text="Chotu ki limit 1 ghanta", learners=[MUNNI, NOT_ALLOWED])
    assert result is not None
    assert result.writes == []
    assert reply_of(result) == COPY[(CopyKey.ASK_CHILD_TALK, H)].body.format(child="Chotu")
    assert [button.id for button in result.reply.buttons] == [
        f"onb:childtalk:yes:{NOT_ALLOWED.id}",
        f"onb:childtalk:no:{NOT_ALLOWED.id}",
    ]


def test_a_limit_button_for_a_child_whose_talk_was_switched_off_sets_nothing() -> None:
    result = settle(
        button=limit_button(DailyTalkLimit.MINUTES_20, NOT_ALLOWED), learners=[NOT_ALLOWED]
    )
    assert result is not None
    assert result.writes == []
    assert result.reply.buttons[0].id == f"onb:childtalk:yes:{NOT_ALLOWED.id}"


def test_with_no_child_who_could_talk_the_message_is_left_to_the_journey() -> None:
    """Child talk is for 3-8: a parent of a 14-year-old who says "limit" is answered instead."""
    assert settle(text="limit hata do", learners=[TEEN]) is None


# --- through the journey -----------------------------------------------------------------------


async def journey(
    text: str, *, khoj: bool = False, child_talk: bool = True
) -> tuple[LayerResult, PromptRoutedLanguageModel]:
    """Intent reading on, with the model scripted to hear "stop the daily message"."""
    layer, llm = layer_with(intent=reading("daily_off"), child_talk=child_talk)
    open_activity = offer(first_choice(), MUNNI) if khoj else None
    ctx = turn_context(text_message(text), learners=[MUNNI], open_activity=open_activity)
    result = await layer.handle(ctx, ParentMessage(text, []), NOW, H)
    return result, llm


async def test_a_typed_limit_never_reaches_the_intent_model() -> None:
    """A setting is read by fixed rules: the model could hear "limit hata do" as "stop the daily
    message" (here it would: its reading is scripted as daily_off)."""
    result, llm = await journey("Munni ka limit hata do")
    assert limit_set(result).limit is DailyTalkLimit.NO_LIMIT
    assert llm.by_prompt["parent_intent"].prompts == []


async def test_with_a_khoj_open_a_typed_limit_isnt_taken_as_a_report() -> None:
    result, llm = await journey("Munni ki limit 1 ghanta kar do", khoj=True)
    assert limit_set(result).limit is DailyTalkLimit.MINUTES_60
    assert llm.by_prompt["parent_reflection"].prompts == []
    assert result.reply.buttons[0].id == KHOJ_DONE


async def test_a_limit_that_isnt_margs_goes_to_intent_reading_as_before() -> None:
    layer, llm = layer_with(intent=reading("question"))
    ctx = turn_context(text_message("NMMS ki age limit kya hai"), learners=[MUNNI])
    result = await layer.handle(ctx, ParentMessage("NMMS ki age limit kya hai", []), NOW, H)
    assert len(llm.by_prompt["parent_intent"].prompts) == 1  # read by the model
    assert not any(isinstance(write, ChildTalkDailyLimit) for write in result.writes)


async def test_with_child_talk_switched_off_the_limit_is_not_offered() -> None:
    result, _ = await journey("Munni ka limit hata do", child_talk=False)
    assert not any(isinstance(write, ChildTalkDailyLimit) for write in result.writes)


# --- right after the yes (onboarding) ---------------------------------------------------


async def test_the_yes_to_child_talk_asks_the_daily_limit_with_its_three_buttons() -> None:
    munni = child(1, "Munni")
    parent = at(ConversationState.ACTIVE, role=Role.PARENT)
    result, _ = await handle(
        parent, button_reply(f"onb:childtalk:yes:{munni.id}"), learners=[munni]
    )
    assert ChildTalkConsent(learner_id=munni.id, granted=True) in result.writes
    body = result.reply.body
    assert body.startswith(COPY[(CopyKey.CHILD_TALK_ENABLED, H)].body.format(child="Munni"))
    assert "Munni roz kitni der Marg se baat karein: 20 minute, 30 minute ya 1 ghanta?" in body
    assert "Abhi: 30 minute." in body  # the default
    assert [button.id for button in result.reply.buttons] == [
        f"jrn:limit:20_minutes:{munni.id}",
        f"jrn:limit:30_minutes:{munni.id}",
        f"jrn:limit:60_minutes:{munni.id}",
    ]
    assert [button.title for button in result.reply.buttons] == [
        DAILY_LIMIT_NAMES[limit][H]
        for limit in (
            DailyTalkLimit.MINUTES_20,
            DailyTalkLimit.MINUTES_30,
            DailyTalkLimit.MINUTES_60,
        )
    ]


async def test_not_now_still_offers_the_khoj_and_asks_no_limit() -> None:
    munni = child(1, "Munni")
    parent = at(ConversationState.ACTIVE, role=Role.PARENT)
    result, _ = await handle(parent, button_reply(f"onb:childtalk:no:{munni.id}"), learners=[munni])
    assert "kitni der" not in result.reply.body
    assert [button.id for button in result.reply.buttons] == ["jrn:today"]


# --- a child can't change it -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "buttons"),
    [
        ("limit hata do", []),
        ("mera limit 1 ghanta kar do", []),
        ("लिमिट हटा दो", []),
        ("", [f"jrn:limit:no_limit:{MUNNI.id}"]),
    ],
)
async def test_in_a_childs_session_the_limit_is_for_mummy_papa(
    text: str, buttons: list[str]
) -> None:
    llm = FakeLanguageModel([CHILD_REPLY])
    layer = ChildTalkLayer(llm, shipped_registry(), LIMITS)
    message = button_reply(buttons[0]) if buttons else text_message(text)
    ctx = turn_context(message, learners=[MUNNI]).model_copy(
        update={"child_session": open_session(MUNNI, turns=1)}
    )
    result = await layer.handle(ctx, text, buttons, NOW, H)
    assert result.reply.body == ASK_A_GROWNUP[H]
    assert result.writes == []
    assert llm.prompts == []


async def test_a_child_asking_about_some_other_limit_gets_an_answer() -> None:
    llm = FakeLanguageModel([CHILD_REPLY])
    layer = ChildTalkLayer(llm, shipped_registry(), LIMITS)
    text = "TV dekhne ki limit kyun hoti hai?"
    ctx = turn_context(text_message(text), learners=[MUNNI]).model_copy(
        update={"child_session": open_session(MUNNI, turns=1)}
    )
    result = await layer.handle(ctx, text, [], NOW, H)
    assert result.reply.body != ASK_A_GROWNUP[H]
    assert len(llm.prompts) == 1


# --- how much time is left today (owner, 2026-11-13) -------------------------------------------

HINT = 'Limit badalni ho toh likhiye "limit badlo".'


def talked(minutes: float, *, learner: Learner = MUNNI, hours_ago: float = 2) -> ChildSessionSpan:
    """A finished session today that ran `minutes` (at most 10 of it counts)."""
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


def used_today(minutes: int, learner: Learner = MUNNI) -> list[ChildSessionSpan]:
    """`minutes` of talk today, in sessions of at most 10 minutes an hour apart."""
    sessions: list[ChildSessionSpan] = []
    for number, start in enumerate(range(0, minutes, 10)):
        sessions.append(talked(min(10, minutes - start), learner=learner, hours_ago=1 + number))
    return sessions


def test_with_no_talk_today_the_whole_limit_is_left() -> None:
    result = settle(text="Munni ka aaj Marg se kitna time bacha hai?")
    assert reply_of(result) == (
        "⏱️ Munni ne aaj abhi tak Marg se baat nahi ki. Roz ki limit 30 minute hai, toh aaj 30"
        f" minute aur baaki hain. {HINT}"
    )


def test_the_time_used_today_and_whats_left_of_the_limit() -> None:
    result = settle(text="Munni ki limit mein kitna time bacha hai?", today=used_today(14))
    assert reply_of(result) == (
        "⏱️ Aaj Munni ne Marg se 14 minute baat ki. Roz ki limit 30 minute hai, toh aaj 16"
        f" minute aur baaki hain. {HINT}"
    )


def test_answering_writes_nothing_and_offers_the_khoj() -> None:
    result = settle(text="aaj Munni ne Marg se kitni der baat ki?", today=used_today(14))
    assert result is not None
    assert result.writes == []
    assert result.reply.buttons == [TODAY_KHOJ_BUTTON[H]]


def test_when_the_time_is_used_up_the_parent_is_told_so() -> None:
    result = settle(text="Munni ka kitna time bacha hai?", today=used_today(30))
    assert reply_of(result) == (
        "⏱️ Aaj Munni ne Marg se 30 minute baat ki. Roz ki 30 minute ki limit poori ho gayi; kal"
        f" phir baat kar sakte hain. {HINT}"
    )


def test_the_parents_pick_is_the_limit_counted_against() -> None:
    munni = MUNNI.model_copy(update={"child_talk_daily_limit": DailyTalkLimit.MINUTES_60})
    result = settle(
        text="Munni ka kitna time bacha hai?", learners=[munni], today=used_today(25, munni)
    )
    assert "Roz ki limit 1 ghanta hai, toh aaj 35 minute aur baaki hain." in reply_of(result)


def test_with_no_limit_the_time_used_is_given_and_no_limit_said() -> None:
    free = MUNNI.model_copy(update={"child_talk_daily_limit": DailyTalkLimit.NO_LIMIT})
    result = settle(
        text="Munni ka kitna time bacha hai?", learners=[free], today=used_today(45, free)
    )
    assert (
        reply_of(result)
        == f"⏱️ Aaj Munni ne Marg se 45 minute baat ki. Roz ki koi limit nahi hai. {HINT}"
    )


def test_under_a_minute_left_is_said_so() -> None:
    almost = [*used_today(20), talked(9 + 40 / 60, hours_ago=4)]  # 29m40s
    result = settle(text="Munni ka kitna time bacha hai?", today=almost)
    assert "toh aaj 1 minute se kam aur baaki hain." in reply_of(result)


def test_yesterdays_and_a_siblings_time_are_not_counted() -> None:
    yesterday = talked(10, hours_ago=30)
    golu_today = used_today(20, GOLU)
    result = settle(
        text="Munni ka kitna time bacha hai?",
        learners=[MUNNI, GOLU],
        today=[yesterday, *golu_today, talked(5)],
    )
    assert "Aaj Munni ne Marg se 5 minute baat ki." in reply_of(result)


def test_with_two_children_it_asks_which_and_each_button_asks_the_time() -> None:
    result = settle(text="limit mein kitna time bacha hai?", learners=[MUNNI, GOLU])
    assert result is not None
    assert reply_of(result) == CHILD_TALK_LIMIT_WHICH_CHILD[H]
    assert [button.id for button in result.reply.buttons] == [
        limit_button("time", MUNNI),
        limit_button("time", GOLU),
    ]
    tapped = settle(
        button=limit_button("time", GOLU), learners=[MUNNI, GOLU], today=used_today(10, GOLU)
    )
    assert reply_of(tapped).startswith("⏱️ Aaj Golu ne Marg se 10 minute baat ki.")
    assert tapped is not None
    assert tapped.writes == []


def test_a_time_button_for_another_accounts_child_answers_nothing_about_them() -> None:
    result = settle(button=f"jrn:limit:time:{UUID(int=99)}")
    assert result is not None
    assert result.writes == []
    assert reply_of(result).startswith("Munni roz kitni der")  # asked again, for her own child


def test_for_a_child_who_may_not_talk_yet_it_asks_the_consent_question() -> None:
    result = settle(
        text="Chotu ka aaj Marg se kitna time bacha hai?", learners=[MUNNI, NOT_ALLOWED]
    )
    assert result is not None
    assert result.reply.buttons[0].id == f"onb:childtalk:yes:{NOT_ALLOWED.id}"


@pytest.mark.parametrize(
    ("language", "start"),
    [
        (
            Language.HINDI,
            "⏱️ आज Munni ने मार्ग से 14 मिनट बात की। रोज़ की लिमिट 30 मिनट है, तो आज 16 मिनट और बाकी हैं।",
        ),
        (
            Language.ENGLISH,
            "⏱️ Munni has talked with Marg for 14 minutes today. The daily limit is 30 minutes,"
            " so there's 16 minutes left today.",
        ),
    ],
)
def test_the_time_left_is_said_in_the_parents_language(language: Language, start: str) -> None:
    result = settle(text="Munni ki limit kitni bachi hai", today=used_today(14), register=language)
    assert reply_of(result).startswith(start)


@pytest.mark.parametrize(
    "text",
    ["Munni ka exam mein kitna time bacha hai", "kitna time bacha hai", "kitna khana bacha hai"],
)
def test_other_time_questions_are_left_to_the_journey(text: str) -> None:
    assert settle(text=text, today=used_today(14)) is None


async def test_a_time_question_never_reaches_the_intent_model() -> None:
    result, llm = await journey("Munni ka aaj Marg se kitna time bacha hai?")
    assert reply_of(result).startswith("⏱️ Munni ne aaj abhi tak Marg se baat nahi ki.")
    assert llm.by_prompt["parent_intent"].prompts == []
