"""ChildSessionRules: start, goodbye, limits and cooldown (s10b §4.16; s05 rules 1a, 6a)."""

from datetime import timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.constants.child_safety_words import (
    CHILD_MANIPULATION_PHRASES,
    CHILD_PERSONAL_TOPICS,
    QUESTION_WORDS,
)
from app.domain.rules.child_reply_matcher import ChildReplyMatcher
from app.domain.rules.child_session_rules import ChildSessionRules
from tests.support.child_talk import LIMITS, consented_child, open_session
from tests.support.turn_context import NOW

pytestmark = pytest.mark.unit

MUNNI = consented_child(1, "Munni")
GOLU = consented_child(2, "Golu", age=7)


@pytest.mark.parametrize(
    ("text", "buttons"),
    [
        ("", ["kid:start"]),
        ("", [f"kid:start:{MUNNI.id}"]),
        ("Main Munni hoon", []),
        ("main munni hu, chaand kyun chamakta hai", []),
        ("Munni bol rahi hoon", []),
        ("Golu bol raha hoon", []),
        ("मैं Munni हूँ", []),
        ("I'm Golu", []),
        # how children actually text (owner's tests, 2026-10-29)
        ("Mein munni hi bol rhi hoon", []),
        ("Hello me munni hoon aaj kya krein", []),
        ("mai Munni hi hoon", []),
        ("Munni hoon", []),
        ("munni toh bol rhi hu", []),
        ("main Munni hooooon", []),
        ("मैं Munni ही हूँ", []),
        ("Munni बोल रही हूं", []),
        ("this is Golu", []),
    ],
)
def test_a_child_starts_with_the_button_or_by_saying_their_name(
    text: str, buttons: list[str]
) -> None:
    assert ChildSessionRules.asks_to_start(text, buttons, [MUNNI, GOLU])


@pytest.mark.parametrize(
    "text",
    [
        "Munni ne kaha chaand kyun",
        "main hoon",
        "Main Chotu hoon",
        "Munnibai bol rahi hoon",
        "",
        # a parent speaking about the child, not the child speaking
        "Munni bol rahi hai ki chaand bada hai",
        "ghar mein Munni bol rahi thi",
        "main Munni ki mummy hoon",
        "main Munni ke liye pooch rahi hoon",
        "Munni bol rahi",
        "Munni hi hai",
    ],
)
def test_other_messages_dont_start_a_session(text: str) -> None:
    assert not ChildSessionRules.asks_to_start(text, [], [MUNNI, GOLU])


def test_the_button_names_the_child() -> None:
    chosen = ChildSessionRules.chosen_learner([f"kid:start:{GOLU.id}"], "", [MUNNI, GOLU])
    assert chosen == GOLU


def test_the_introduction_names_the_child() -> None:
    assert ChildSessionRules.chosen_learner([], "Golu bol raha hoon", [MUNNI, GOLU]) == GOLU


def test_with_one_child_a_bare_button_means_them() -> None:
    assert ChildSessionRules.chosen_learner(["kid:start"], "", [MUNNI]) == MUNNI


def test_with_several_children_a_bare_button_cant_tell() -> None:
    assert ChildSessionRules.chosen_learner(["kid:start"], "", [MUNNI, GOLU]) is None


def test_a_button_naming_someone_elses_child_is_ignored() -> None:
    assert ChildSessionRules.chosen_learner(["kid:start:not-a-child"], "", [MUNNI, GOLU]) is None


@pytest.mark.parametrize("text", ["bye", "Bye bye!", "bas", "Tata", "बस", "alvida"])
def test_a_goodbye_ends(text: str) -> None:
    assert ChildSessionRules.says_goodbye(text)


@pytest.mark.parametrize("text", ["bas ek sawaal aur", "bye kyun bolte hain?", ""])
def test_a_goodbye_word_inside_a_question_does_not(text: str) -> None:
    assert not ChildSessionRules.says_goodbye(text)


@pytest.mark.parametrize(("turns", "minutes"), [(6, 0), (0, 10), (5, 10), (9, 30)])
def test_a_session_is_over_at_the_turn_or_time_limit_exactly(turns: int, minutes: int) -> None:
    session = open_session(MUNNI, turns=turns, started=NOW - timedelta(minutes=minutes))
    assert ChildSessionRules.is_over(session, NOW, LIMITS)


@pytest.mark.parametrize(("turns", "minutes"), [(0, 0), (5, 9)])
def test_a_session_under_both_limits_goes_on(turns: int, minutes: int) -> None:
    session = open_session(MUNNI, turns=turns, started=NOW - timedelta(minutes=minutes))
    assert not ChildSessionRules.is_over(session, NOW, LIMITS)


def test_the_sixth_turn_is_the_last_and_the_fifth_is_not() -> None:
    assert ChildSessionRules.is_last_turn(open_session(MUNNI, turns=5), LIMITS)
    assert not ChildSessionRules.is_last_turn(open_session(MUNNI, turns=4), LIMITS)


def test_a_new_session_waits_30_minutes_after_the_last() -> None:
    assert ChildSessionRules.in_cooldown(NOW - timedelta(minutes=29), NOW, LIMITS)
    assert not ChildSessionRules.in_cooldown(NOW - timedelta(minutes=30), NOW, LIMITS)
    assert not ChildSessionRules.in_cooldown(None, NOW, LIMITS)


@given(turns=st.integers(0, 20), minutes=st.integers(0, 60))
def test_once_over_more_turns_or_time_keep_it_over(turns: int, minutes: int) -> None:
    session = open_session(MUNNI, turns=turns, started=NOW - timedelta(minutes=minutes))
    later = open_session(MUNNI, turns=turns + 1, started=NOW - timedelta(minutes=minutes + 1))
    if ChildSessionRules.is_over(session, NOW, LIMITS):
        assert ChildSessionRules.is_over(later, NOW, LIMITS)


# --- what a reply to a child must never say (s07 d8, d1 child rule) -------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        "Haan, yeh hamara secret hai",
        "Kisi ko mat batana!",
        "Main tumhara best friend hoon",
        "Only I understand you.",
        "यह किसी को मत बताना",
    ],
)
def test_secrecy_and_attachment_are_caught(reply: str) -> None:
    assert ChildReplyMatcher.manipulates(reply, CHILD_MANIPULATION_PHRASES)


@pytest.mark.parametrize(
    "reply", ["Mummy-Papa ko bhi batana!", "Tumne bahut accha dekha.", "Tell your teacher too."]
)
def test_kind_replies_are_not(reply: str) -> None:
    assert not ChildReplyMatcher.manipulates(reply, CHILD_MANIPULATION_PHRASES)


@pytest.mark.parametrize(
    "reply",
    [
        "Tumhara school kaunsa hai?",
        "Ghar ka phone number kya hai?",
        "Papa ka naam kya hai?",
        "Which village do you live in?",
        "तुम्हारा स्कूल कहाँ है?",
    ],
)
def test_questions_for_personal_details_are_caught(reply: str) -> None:
    assert ChildReplyMatcher.asks_personal_details(reply, QUESTION_WORDS, CHILD_PERSONAL_TOPICS)


@pytest.mark.parametrize(
    "reply",
    [
        "Munni, tumne kya dekha?",
        "School mein bhi patte dekhna!",
        "Kitne patte mile? Ginti karo.",
        "Teacher ko bhi batana.",
    ],
)
def test_ordinary_questions_and_mentions_are_not(reply: str) -> None:
    assert not ChildReplyMatcher.asks_personal_details(reply, QUESTION_WORDS, CHILD_PERSONAL_TOPICS)


# Words a parent uses about a child, in Roman, Devanagari and emoji: none of them first person.
ABOUT_THE_CHILD = [
    "Munni", "Golu", "bol", "rahi", "rhi", "raha", "hai", "thi", "hi", "toh", "main", "mein",
    "me", "ki", "ne", "kaha", "mummy", "ghar", "बोल", "रही", "है", "ही", "मैं", "🙂", "?",
]  # fmt: skip


@given(words=st.lists(st.sampled_from(ABOUT_THE_CHILD), max_size=10))
def test_without_a_first_person_word_no_session_starts(words: list[str]) -> None:
    assert not ChildSessionRules.asks_to_start(" ".join(words), [], [MUNNI, GOLU])
