"""ChildTalkLimitParser: a parent typing about a child's daily talk limit (s10b §4.16; owner,
2026-11-13: 20 minutes, 30 minutes, 1 hour, or no limit, which is typed only)."""

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from app.constants.child_talk_copy import DAILY_LIMIT_NAMES
from app.domain.enums import DailyTalkLimit, Language
from app.domain.rules.child_talk_limit_parser import ChildTalkLimitParser
from tests.support.child_talk import consented_child

pytestmark = pytest.mark.unit

MUNNI = consented_child(1, "Munni")
GOLU = consented_child(2, "Golu", age=7)
NAMELESS = consented_child(3, None)
CHILDREN = [MUNNI, GOLU, NAMELESS]


@pytest.mark.parametrize(
    ("text", "limit"),
    [
        # no limit: typed only (owner, 2026-11-13)
        ("Munni ka limit hata do", DailyTalkLimit.NO_LIMIT),
        ("munni ki limit hatao", DailyTalkLimit.NO_LIMIT),
        ("limit hata dijiye", DailyTalkLimit.NO_LIMIT),
        ("koi limit nahi", DailyTalkLimit.NO_LIMIT),
        ("limit nahi chahiye", DailyTalkLimit.NO_LIMIT),
        ("no limit", DailyTalkLimit.NO_LIMIT),
        ("remove the limit", DailyTalkLimit.NO_LIMIT),
        ("remove Munni's limit please", DailyTalkLimit.NO_LIMIT),
        ("लिमिट हटा दो", DailyTalkLimit.NO_LIMIT),
        ("मुन्नी की लिमिट नहीं चाहिए", DailyTalkLimit.NO_LIMIT),
        # the three on buttons, typed
        ("limit 20 minute kar do", DailyTalkLimit.MINUTES_20),
        ("Munni ki limit bees minute", DailyTalkLimit.MINUTES_20),
        ("limit 20min", DailyTalkLimit.MINUTES_20),
        ("लिमिट बीस मिनट", DailyTalkLimit.MINUTES_20),
        ("limit 30 minute", DailyTalkLimit.MINUTES_30),
        ("limit aadha ghanta", DailyTalkLimit.MINUTES_30),
        ("set the limit to half an hour", DailyTalkLimit.MINUTES_30),
        ("लिमिट आधा घंटा", DailyTalkLimit.MINUTES_30),
        ("limit 1 ghanta", DailyTalkLimit.MINUTES_60),
        ("munni ki limit ek ghanta kar do", DailyTalkLimit.MINUTES_60),
        ("limit 60 min", DailyTalkLimit.MINUTES_60),
        ("make the limit one hour", DailyTalkLimit.MINUTES_60),
        ("मुन्नी की लिमिट एक घंटा कर दो", DailyTalkLimit.MINUTES_60),
    ],
)
def test_a_limit_typed_in_any_language_is_read(text: str, limit: DailyTalkLimit) -> None:
    assert ChildTalkLimitParser.is_about_the_limit(text, CHILDREN)
    assert ChildTalkLimitParser.limit_named(text) is limit


@pytest.mark.parametrize(
    "text",
    [
        "limit 45 minute kar do",
        "limit 2 ghante",
        "limit do ghante",
        "limit 10 minute",
        "limit 90 min",
        "लिमिट दो घंटे",
        # an hour and a bit is not an hour: never rounded to the nearest choice
        "limit 1 ghanta 15 minute",
        "limit ek ghanta aur 30 minute",
        "limit 1 hour 20 minutes",
    ],
)
def test_a_time_that_isnt_a_choice_names_nothing_and_is_never_rounded(text: str) -> None:
    assert ChildTalkLimitParser.is_about_the_limit(text, CHILDREN)
    assert ChildTalkLimitParser.limit_named(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "limit 20 minute se 30 minute kar do",  # two choices
        "1 ghante ki limit hata do",  # a time and no limit
        "limit badlo",
        "limit kitna hai?",
        "change limit",
        "limit",
        "LIMIT!!!",
        # the short commands Marg's replies teach, with a child's name
        "Munni ki limit badlo",
        "Golu ki limit kitni hai?",
        "what is the limit?",
        "Munni की लिमिट कितनी है?",
        "meri beti ki limit badhao",
        # about talking to Marg, with no value
        "Marg se baat karne ki limit kya hai",
        "munni ki Marg wali limit badalni hai kya?",
    ],
)
def test_a_message_about_the_limit_without_one_clear_choice_names_nothing(text: str) -> None:
    assert ChildTalkLimitParser.is_about_the_limit(text, CHILDREN)
    assert ChildTalkLimitParser.limit_named(text) is None


@pytest.mark.parametrize(
    "text",
    [
        # says "limit", but about something else (owner, 2026-11-13: be precise)
        "Munni ki TV limit 1 ghanta theek hai?",
        "mobile ki limit kitni rakhein",
        "screen time limit kitna hona chahiye 5 saal ke bachche ke liye",
        "NMMS ki age limit kya hai",
        "scholarship ki income limit kitni hai",
        "khane mein cheeni ki limit",
        "Munni ka TV limit hata do",
        "Marg se baat karne ki mobile limit",  # both: left unread, never guessed
        # says "limit" with no value, no Marg and not a short command: the parent's question
        "kya bachchon ke liye koi limit honi chahiye?",
        "limit se zyada mat khilao",
        "bachche ki limit samajhna zaroori hai",
        "Munni ki limit kitni honi chahiye padhai ki",
        "limit 20 se 30 kar do",  # numbers with no unit carry no time
        "मुन्नी की लिमिट कितनी है?",  # not the name on the list ("Munni"), so not a command
        "Munni ko 1 ghanta baat karne do",  # no "limit": left to the journey
        "aaj 20 minute khela",
        "khoj hata do",
        "",
        "   ",
        "🙂🙂",
        "limited edition",  # a longer word, not "limit"
    ],
)
def test_a_message_that_doesnt_say_limit_is_not_about_it(text: str) -> None:
    assert not ChildTalkLimitParser.is_about_the_limit(text, CHILDREN)


@pytest.mark.parametrize(
    "text",
    [
        "kya 1 ghanta ki limit theek hai?",
        "क्या 20 मिनट की लिमिट सही है",
        "should the limit be 30 minutes",
        "Munni ki limit hata do?",
        "limit 1 ghanta kar du?",
    ],
)
def test_a_question_is_told_apart_so_it_never_sets_a_limit(text: str) -> None:
    assert ChildTalkLimitParser.is_about_the_limit(text, CHILDREN)
    assert ChildTalkLimitParser.asks_a_question(text)


@pytest.mark.parametrize(
    "text", ["Munni ka limit hata do", "limit 1 ghanta kar do", "लिमिट आधा घंटा", "no limit"]
)
def test_an_instruction_is_not_a_question(text: str) -> None:
    assert not ChildTalkLimitParser.asks_a_question(text)


def test_a_childs_name_only_counts_for_a_child_on_the_list() -> None:
    """ "Pinki ki limit badlo" with no Pinki: "pinki" is a word the command doesn't have."""
    assert not ChildTalkLimitParser.is_about_the_limit("Pinki ki limit badlo", CHILDREN)
    assert ChildTalkLimitParser.is_about_the_limit("Munni ki limit badlo", CHILDREN)


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("Munni ka limit hata do", MUNNI),
        ("golu ki limit 1 ghanta", GOLU),
        ("limit hata do", None),
        ("Munni aur Golu ki limit hata do", None),  # two: say which, not both
        ("Munnibai ki limit", None),  # whole words only
    ],
)
def test_the_child_is_the_one_whose_name_is_said(text: str, named: object) -> None:
    assert ChildTalkLimitParser.child_named(text, [MUNNI, GOLU, NAMELESS]) == named


@pytest.mark.parametrize("language", list(Language))
@pytest.mark.parametrize("limit", list(DailyTalkLimit))
def test_every_limit_marg_names_typed_back_is_understood(
    limit: DailyTalkLimit, language: Language
) -> None:
    """What the buttons and replies say ("1 ghanta", "कोई लिमिट नहीं") reads back as itself."""
    typed = f"limit {DAILY_LIMIT_NAMES[limit][language]}"
    assert ChildTalkLimitParser.limit_named(typed) is limit


_words = st.sampled_from(
    [
        "limit", "लिमिट", "hata", "do", "20", "minute", "1", "ghanta", "aadha", "half", "an",
        "hour", "मिनट", "घंटा", "बीस", "nahi", "chahiye", "Munni", "ki", "🙂", "ok", "45", "",
    ]
)  # fmt: skip
_messages = st.one_of(
    st.text(max_size=80),
    st.lists(_words, max_size=10).map(" ".join),
)


@given(text=_messages)
@example(text="limit 20 20 minute")
@example(text="minute")
@example(text="limit ½ ghanta")
def test_any_message_reads_as_one_choice_or_none_and_never_raises(text: str) -> None:
    named = ChildTalkLimitParser.limit_named(text)
    assert named is None or named in DailyTalkLimit


@given(text=_messages)
def test_without_the_word_limit_a_message_is_never_about_it(text: str) -> None:
    words = text.casefold().split()
    says_limit = any("limit" in word or "लिमिट" in word for word in words)
    if not says_limit:
        assert not ChildTalkLimitParser.is_about_the_limit(text, CHILDREN)


@given(text=_messages, subject=st.sampled_from(["TV", "mobile", "age", "khana", "टीवी"]))
def test_a_limit_on_something_else_is_never_marg_s(text: str, subject: str) -> None:
    assert not ChildTalkLimitParser.is_about_the_limit(f"{subject} {text} limit", CHILDREN)


# --- how much time is left today (owner, 2026-11-13) -------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Munni ki limit mein kitna time bacha hai?",
        "Munni ka Marg se baat karne ka kitna time bacha hai?",
        "aaj Munni ne Marg se kitni der baat ki?",
        "Munni ka aaj kitna time bacha hai?",  # the child's name and a time word
        "how much time does Munni have left today?",
        "how long did Munni talk to Marg today?",
        "Munni ki limit kitni bachi hai",
        "मुन्नी की लिमिट में कितना समय बचा है?",
        "aaj kitni der baat hui Marg se",
        "limit mein kitne minute baaki hain",
    ],
)
def test_asking_how_much_time_is_left_or_used_today_is_read(text: str) -> None:
    assert ChildTalkLimitParser.asks_time_left(text, CHILDREN)


@pytest.mark.parametrize(
    "text",
    [
        "Munni ka exam mein kitna time bacha hai",  # another subject
        "Munni ke school jaane mein kitna time bacha hai",
        "kitna khana bacha hai",
        "Munni aaj kitna khush thi",  # no time word
        "kitna time bacha hai",  # no child, no Marg, no limit: not clearly Marg's
        "Munni ki limit kitni hai?",  # the limit itself, not what's left
        "limit badlo",
        "Munni ka limit hata do",
        "",
        "🙂",
    ],
)
def test_other_messages_are_not_about_the_time_left(text: str) -> None:
    assert not ChildTalkLimitParser.asks_time_left(text, CHILDREN)


@given(text=_messages, subject=st.sampled_from(["TV", "exam", "school", "khana", "टीवी"]))
def test_time_left_on_something_else_is_never_margs(text: str, subject: str) -> None:
    assert not ChildTalkLimitParser.asks_time_left(f"{subject} {text} kitna bacha", CHILDREN)
