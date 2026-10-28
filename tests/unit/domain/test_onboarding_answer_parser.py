"""OnboardingAnswerParser: common answers read without a model (s08 §4.4 step 4, §9)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.enums import Language, Role
from app.domain.rules.onboarding_answer_parser import Found, OnboardingAnswerParser

pytestmark = pytest.mark.unit

P = OnboardingAnswerParser
YEAR = 2026


@pytest.mark.parametrize(
    "text", ["hi", "Hello!", "namaste", "नमस्ते", "हेलो", "Hello ji 🙏", "😊", ""]
)
def test_greetings(text: str) -> None:
    assert P.is_greeting(text)


@pytest.mark.parametrize("text", ["mujhe pilot banna hai", "hi, beta khana nahi khata"])
def test_a_question_is_not_a_greeting(text: str) -> None:
    assert not P.is_greeting(text)


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("haan", True), ("Haan ji", True), ("ok", True), ("हाँ, ठीक है", True), ("yes", True),
        ("nahi", False), ("no", False), ("नहीं", False), ("mat karo", False),
        ("haan nahi", None), ("pata nahi kya karna hai iska abhi", None), ("Munni", None),
    ],
)  # fmt: skip
def test_yes_or_no(text: str, *, said: bool | None) -> None:
    assert P.yes_or_no(text) is said


@pytest.mark.parametrize(
    ("text", "role"),
    [
        ("Main parent hoon", Role.PARENT), ("mummy", Role.PARENT), ("माता-पिता", Role.PARENT),
        ("teacher", Role.TEACHER), ("मैं शिक्षक हूँ", Role.TEACHER), ("student", Role.STUDENT),
        ("mummy aur teacher dono", None), ("kuch nahi", None),
    ],
)  # fmt: skip
def test_role_named(text: str, role: Role | None) -> None:
    assert P.role_named(text) is role


@pytest.mark.parametrize(
    ("text", "grade"),
    [("9", 9), ("9th", 9), ("class 9", 9), ("kaksha 9", 9), ("नौवीं", 9), ("12", 12), ("1", 1)],
)
def test_grades(text: str, grade: int) -> None:
    assert P.parse_grade(text).grade == grade


@pytest.mark.parametrize("text", ["class 13", "0", "25"])
def test_a_grade_outside_1_to_12_is_reported_not_repaired(text: str) -> None:
    assert P.parse_grade(text).problem is Found.OUT_OF_RANGE


@pytest.mark.parametrize(
    ("text", "birth_year"),
    [
        ("5 saal", 2021), ("5 years", 2021), ("paanch saal", 2021), ("पाँच साल", 2021),
        ("पांच साल", 2021), ("2019", 2019), ("beti, Munni, 4 saal ki", 2022), ("३ साल", 2023),
    ],
)  # fmt: skip
def test_child_ages(text: str, birth_year: int) -> None:
    assert P.parse_child_age(text, YEAR).birth_year == birth_year


@pytest.mark.parametrize("text", ["1", "25", "40 saal", "1990"])
def test_an_age_outside_2_to_19_is_reported(text: str) -> None:
    assert P.parse_child_age(text, YEAR).problem is Found.OUT_OF_RANGE


@pytest.mark.parametrize("text", ["beti hai", "Munni", "do baar bola"])
def test_no_age_is_absent_not_guessed(text: str) -> None:
    assert P.parse_child_age(text, YEAR).problem is Found.ABSENT


@pytest.mark.parametrize(
    ("text", "nickname"),
    [
        ("beti, Munni, 5 saal", "Munni"),
        ("मुन्नी 4 साल", "मुन्नी"),
        ("golu", "golu"),
        ("beta 5 saal", None),
    ],
)
def test_nicknames(text: str, nickname: str | None) -> None:
    assert P.parse_nickname(text).nickname == nickname


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("Priya Kumari Sharma, 6 saal", Found.LOOKS_LIKE_FULL_NAME),
        ("Rahul Verma", Found.LOOKS_LIKE_FULL_NAME),
        ("राम कुमार शर्मा", Found.LOOKS_LIKE_FULL_NAME),
        ("x" * 21, Found.TOO_LONG),
        ("beti 5 saal", Found.ABSENT),
    ],
)
def test_full_names_and_long_names_are_refused(text: str, problem: Found) -> None:
    assert P.parse_nickname(text).problem is problem


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("English", Language.ENGLISH), ("hindi", Language.HINGLISH), ("हिंदी", Language.HINDI),
        ("हिंदी में", Language.HINDI), ("in english please", Language.ENGLISH),
        ("Hinglish", Language.HINGLISH), ("english is hard for my son", None), ("hello", None),
    ],
)  # fmt: skip
def test_a_message_that_is_only_a_language_name(text: str, language: Language | None) -> None:
    assert P.language_named(text) is language


@pytest.mark.parametrize(
    "text",
    [
        "mera data hatao", "Delete my data!", "मेरा डेटा हटाओ", "consent wapas", "data delete karo",
        "Mera saara data hata do",  # regression: the eval's onboarding-004 reached the mentor
        "please remove my data", "सारा डेटा हटा दो",
    ],
)  # fmt: skip
def test_deletion_phrases(text: str) -> None:
    assert P.asks_for_deletion(text)


@pytest.mark.parametrize("text", ["stop", "roz ka message band karo", "delete", "data"])
def test_bare_stop_or_delete_is_not_a_deletion_request(text: str) -> None:
    assert not P.asks_for_deletion(text)


@given(age=st.integers(2, 19), filler=st.sampled_from(["", "beti ", "Munni, ", "मेरा बेटा "]))
def test_any_valid_age_in_years_gives_its_birth_year(age: int, filler: str) -> None:
    assert P.parse_child_age(f"{filler}{age} saal", YEAR).birth_year == YEAR - age


@given(text=st.text(max_size=80))
def test_the_parser_never_crashes_and_never_invents_an_out_of_range_value(text: str) -> None:
    grade = P.parse_grade(text)
    assert grade.grade is None or grade.grade in P.GRADES
    age = P.parse_child_age(text, YEAR)
    assert age.birth_year is None or YEAR - age.birth_year in P.CHILD_AGES
    nickname = P.parse_nickname(text)
    assert nickname.nickname is None or len(nickname.nickname) <= P.NICKNAME_MAX_CHARS
