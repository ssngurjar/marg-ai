"""OnboardingAnswerParser: common answers read without a model (s08 §4.4 step 4, §9)."""

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from app.domain.enums import Language, Role
from app.domain.rules.onboarding_answer_parser import (
    ChildParse,
    ChildrenParse,
    Found,
    GradeParse,
    OnboardingAnswerParser,
)

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


@pytest.mark.parametrize(
    ("text", "age"),
    [
        ("saadhe teen saal", 3), ("Munni saadhe teen saal ki hai", 3), ("sawa paanch saal", 5),
        ("paune chaar saal", 3), ("dhai saal ka hai", 2), ("साढ़े तीन साल", 3),
        ("सवा पाँच साल की है", 5), ("पौने चार साल", 3), ("ढाई साल", 2),
    ],
)  # fmt: skip
def test_a_spoken_half_or_quarter_counts_the_whole_years(text: str, age: int) -> None:
    # critic review, 2026-11-01: "saadhe teen saal" saved the nickname "saadhe"
    assert P.parse_child_age(text, YEAR).birth_year == YEAR - age


@pytest.mark.parametrize(
    "text", ["saadhe teen saal", "sawa paanch saal", "paune chaar saal", "ढाई साल", "dedh saal"]
)
def test_half_and_quarter_words_are_never_a_nickname(text: str) -> None:
    assert P.parse_nickname(text).problem is Found.ABSENT


def test_one_and_a_half_years_is_under_two_and_out_of_range() -> None:
    assert P.parse_child_age("dedh saal", YEAR).problem is Found.OUT_OF_RANGE


@pytest.mark.parametrize("text", ["2 saal", "do saal ki hai", "दो साल"])
def test_two_years_is_a_valid_age(text: str) -> None:
    # critic review, 2026-11-01, checked: ages 2-19 are accepted (a parent of a two-year-old is
    # told the khoj is for 3-8), so "2 saal" is never refused
    assert P.parse_child_age(text, YEAR).birth_year == YEAR - 2


@pytest.mark.parametrize("text", ["1", "25", "40 saal", "1990"])
def test_an_age_outside_2_to_19_is_reported(text: str) -> None:
    assert P.parse_child_age(text, YEAR).problem is Found.OUT_OF_RANGE


@pytest.mark.parametrize(
    "text", ["abhi 6 mahine ka hai", "18 months old", "८ महीने", "baby hai, 9 mahina"]
)
def test_an_age_in_months_is_under_two_and_out_of_range(text: str) -> None:
    # onboarding bank, 2026-11-01: "6 mahine" was read as six years, named "mahine"
    assert P.parse_child_age(text, YEAR).problem is Found.OUT_OF_RANGE


def test_years_and_months_together_count_the_years() -> None:
    assert P.parse_child_age("2 saal 6 mahine", YEAR).birth_year == YEAR - 2


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
    "text",
    ["Mera baccha 6 saal ka hai", "meri bacchi 5 saal ki hai", "mera bachha 4 saal", "bacche 7"],
)
def test_the_ways_parents_spell_child_are_never_a_nickname(text: str) -> None:
    # owner's demo, 2026-11-01: "Mera baccha 6 saal ka hai" saved the nickname "baccha"
    assert P.parse_nickname(text).nickname is None


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


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Hi Marg, English please", Language.ENGLISH),  # the judges' WhatsApp link (2026-10-29)
        ("Hello, English", Language.ENGLISH),
        ("English", Language.ENGLISH),
        ("Namaste, Hindi mein", Language.HINGLISH),  # "Hindi" in Roman letters is Hinglish
        ("hinglish pls", Language.HINGLISH),
    ],
)
def test_a_greeting_that_names_a_language_requests_it(text: str, language: Language) -> None:
    assert OnboardingAnswerParser.language_requested(text) is language


@pytest.mark.parametrize(
    "text", ["Hi", "I teach English", "English aur Hindi", "Mujhe English seekhni hai", ""]
)
def test_anything_more_than_a_greeting_and_one_language_is_not_a_request(text: str) -> None:
    assert OnboardingAnswerParser.language_requested(text) is None


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Hindi pleasee", Language.HINGLISH),  # owner's demo, 2026-10-29: stayed in English
        ("Hindii", Language.HINGLISH),
        ("hindi mein baat karo", Language.HINGLISH),
        ("Talk to me in English", Language.ENGLISH),
        ("मुझसे हिंदी में बात कीजिए", Language.HINDI),
        ("अंग्रेज़ी में", Language.ENGLISH),
        ("English plzzz", Language.ENGLISH),
    ],
)
def test_asking_for_a_language_in_ones_own_words_is_understood(
    text: str, language: Language
) -> None:
    assert OnboardingAnswerParser.language_named(text) is language


@pytest.mark.parametrize(
    "text", ["I teach Hindi", "Mujhe English seekhni hai", "Hindi ya English?"]
)
def test_a_sentence_about_a_language_is_not_a_switch(text: str) -> None:
    assert OnboardingAnswerParser.language_named(text) is None


@pytest.mark.parametrize("text", ["Hellooo", "Hiii", "Helo ji", "namasteee"])
def test_stretched_greetings_are_greetings(text: str) -> None:
    assert OnboardingAnswerParser.is_greeting(text)


# --- several children in one answer (critic review D3, 2026-11-01) -----------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Munni 5 aur Golu 7", "Munni 5, Golu 7", "Munni 5 saal aur Golu 7 saal",
        "Munni 5 or Golu 7",
        "5 saal ki Munni aur 7 saal ka Golu", "Meri 2 betiyan hain, Munni 5 aur Golu 7",
        "do bachche hain: Munni 5 and Golu 7",
    ],
)  # fmt: skip
def test_two_named_children_are_both_read(text: str) -> None:
    assert P.parse_children(text, YEAR) == ChildrenParse(
        (ChildParse(YEAR - 5, "Munni"), ChildParse(YEAR - 7, "Golu")), None
    )


def test_two_children_in_devanagari_are_both_read() -> None:
    assert P.parse_children("मुन्नी 5 साल और गोलू 7 साल", YEAR) == ChildrenParse(
        (ChildParse(YEAR - 5, "मुन्नी"), ChildParse(YEAR - 7, "गोलू")), None
    )


@pytest.mark.parametrize(
    "text",
    [
        "Munni 5 saal", "beti, Munni, 5 saal", "Munni 5 saal ki hai aur class 1 mein hai",
        "beti 5 aur beta 7", "2 bachche hain", "",
    ],
)  # fmt: skip
def test_one_child_or_unnamed_children_are_left_to_the_one_child_rules(text: str) -> None:
    assert P.parse_children(text, YEAR) is None


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("Munni 5 aur Golu 1", Found.OUT_OF_RANGE),
        ("Munni 5 aur Golu 6 mahine", Found.OUT_OF_RANGE),
        ("Munni 5 aur Priya Sharma 7", Found.LOOKS_LIKE_FULL_NAME),
    ],
)  # fmt: skip
def test_one_bad_child_among_several_is_reported_not_dropped(text: str, problem: Found) -> None:
    assert P.parse_children(text, YEAR) == ChildrenParse((), problem)


NAMES = st.sampled_from(["Munni", "Golu", "Chotu", "Pinky", "मुन्नी", "गोलू", "lali", "Gudiya"])
JOINERS = st.sampled_from([" aur ", ", ", " and ", " और ", " & "])


@given(
    children=st.lists(
        st.tuples(NAMES, st.integers(2, 19)),
        min_size=2,
        max_size=3,
        unique_by=lambda child: child[0],
    ),
    joiner=JOINERS,
    unit=st.sampled_from(["", " saal", " years", " साल"]),
)
def test_any_named_children_with_ages_are_read_in_order(
    children: list[tuple[str, int]], joiner: str, unit: str
) -> None:
    text = joiner.join(f"{name} {age}{unit}" for name, age in children)
    assert P.parse_children(text, YEAR) == ChildrenParse(
        tuple(ChildParse(YEAR - age, name) for name, age in children), None
    )


@pytest.mark.parametrize("text", ["Ok", "okay", "ok ji", "theek hai", "thank you", "हाँ जी", "Hmm"])
def test_short_acknowledgements_are_recognised(text: str) -> None:
    assert P.is_acknowledgement(text)


@pytest.mark.parametrize(
    "text", ["", "Ok what is this", "haan mera beta 5 saal ka hai", "kya hai ye", "🙏"]
)
def test_anything_more_than_an_acknowledgement_is_not_one(text: str) -> None:
    assert not P.is_acknowledgement(text)


@pytest.mark.parametrize(
    "text",
    ["mai graduate hun", "arey graduation ho gyi", "college mein hoon", "BA final year", "ग्रेजुएट हूँ"],
)
def test_a_student_past_class_12_is_recognised(text: str) -> None:
    # owner's field test, 2026-11-01: "mai graduate hun" got "samajh nahi aaya" three times
    assert P.is_graduate(text)


@pytest.mark.parametrize("text", ["class 12", "12", "baarahvi", "kuch samajh nahi aata", ""])
def test_a_school_class_or_other_words_are_not_graduate(text: str) -> None:
    assert not P.is_graduate(text)


@pytest.mark.parametrize(
    "text", ["kya aap braj bhasha mein baat kar sakte ho", "Braj aati hai?", "ब्रज में बात करोगे?"]
)
def test_a_question_about_braj_is_recognised(text: str) -> None:
    # owner's field test, 2026-11-01: it got the general "what Marg does" paragraph
    assert P.asks_about_braj(text)


@pytest.mark.parametrize("text", ["Hindi mein baat karo", "mera beta 5 saal ka hai", ""])
def test_other_messages_are_not_about_braj(text: str) -> None:
    assert not P.asks_about_braj(text)


# --- a class as a word, or a range a teacher teaches (owner's field test, 2026-11-02) ----------


@pytest.mark.parametrize(
    ("text", "grade"),
    [
        ("दो से आठ।", 8), ("कक्षा तीन से नौ।", 9), ("2 se 9", 9), ("6-8", 8), ("6 to 8", 8),
        ("आठ", 8), ("kaksha das", 10), ("class 8 mein 40 bachche", 8), ("class 8", 8),
    ],
)  # fmt: skip
def test_a_class_in_words_or_a_range_is_read(text: str, grade: int) -> None:
    assert P.parse_grade(text) == GradeParse(grade, None)


def test_a_range_past_class_12_is_out_of_range_not_cut_short() -> None:
    assert P.parse_grade("1 se 15").problem is Found.OUT_OF_RANGE


@given(
    low=st.integers(1, 11), high=st.integers(2, 12), joiner=st.sampled_from([" se ", " to ", "-"])
)
def test_any_range_is_its_highest_class(low: int, high: int, joiner: str) -> None:
    assume(low < high)  # "8 se 6" is not a range
    assert P.parse_grade(f"{low}{joiner}{high}") == GradeParse(high, None)
