"""RegisterDetector: which register to reply in, read from the message itself (S5 decision 3)."""

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from app.domain.enums import Language
from app.domain.rules.register_detector import RegisterDetector

pytestmark = pytest.mark.unit

DEVANAGARI_WORDS = st.sampled_from(["बच्चा", "खेल", "पढ़ाई", "क्या", "नमस्ते", "श्री", "पत्ते"])
ENGLISH_WORDS = st.sampled_from(["child", "play", "school", "today", "learn", "colours", "NEET"])
NO_LETTERS = st.sampled_from(["😊", "👍🏽", "🇮🇳", "123", "?!", " ", "\n", "...", "₹50", "❤️"])


@pytest.mark.parametrize(
    ("text", "register"),
    [
        ("मेरा बच्चा खेलता नहीं है", Language.HINDI),
        ("मेरे बच्चे को NEET के बारे में बताइए", Language.HINDI),  # Roman exam name, Hindi message
        ("Mera bachcha khelta nahi hai", Language.HINGLISH),
        ("BETA KO KYA SIKHAYEIN", Language.HINGLISH),  # all caps
        ("My child won't play with others", Language.ENGLISH),
        ("How can I help my daughter learn colours?", Language.ENGLISH),
    ],
)
def test_detects_the_register_a_parent_writes_in(text: str, register: Language) -> None:
    assert RegisterDetector.detect(text) is register


@pytest.mark.parametrize("text", ["", "   ", "😊😊", "👍🏽", "123 456", "?!", "\n\t"])
def test_a_message_without_letters_has_no_register(text: str) -> None:
    assert RegisterDetector.detect(text) is None


def test_hindi_needs_at_least_half_the_letters_in_devanagari() -> None:
    assert RegisterDetector.detect("ab कख") is Language.HINDI  # exactly half
    assert RegisterDetector.detect("abc कख") is Language.ENGLISH  # under half, no Hinglish word


def test_devanagari_share_is_none_without_letters_and_a_fraction_otherwise() -> None:
    assert RegisterDetector.devanagari_share("😊 123") is None
    assert RegisterDetector.devanagari_share("ab कख") == 0.5


@given(words=st.lists(DEVANAGARI_WORDS, min_size=1, max_size=20), noise=st.lists(NO_LETTERS))
@example(words=["क्या"], noise=["😊"])
def test_devanagari_letters_with_emoji_and_digits_are_always_hindi(
    words: list[str], noise: list[str]
) -> None:
    assert RegisterDetector.detect(" ".join(words + noise)) is Language.HINDI


@given(words=st.lists(ENGLISH_WORDS, min_size=1, max_size=20), noise=st.lists(NO_LETTERS))
def test_roman_text_without_hindi_words_is_english(words: list[str], noise: list[str]) -> None:
    assert RegisterDetector.detect(" ".join(words + noise)) is Language.ENGLISH


@given(noise=st.lists(NO_LETTERS, max_size=10))
def test_emoji_digits_and_punctuation_alone_never_get_a_register(noise: list[str]) -> None:
    assert RegisterDetector.detect("".join(noise)) is None


@given(text=st.text(max_size=200))
def test_detection_is_total_and_deterministic(text: str) -> None:
    assert RegisterDetector.detect(text) == RegisterDetector.detect(text)
    share = RegisterDetector.devanagari_share(text)
    assert share is None or 0.0 <= share <= 1.0


# --- a word half Roman, half Devanagari (owner's field test, 2026-11-01: "Kaटोरा") ----------------


def test_a_mixed_script_word_is_a_problem_for_the_repair_turn() -> None:
    problems = RegisterDetector.script_problems(
        "1. Kaटोरा par katora rakhiye, aur bachche ke saath dekhiye",
        "फ़र्श पर कटोरा रखिए",
        Language.HINGLISH,
    )
    assert 'text: a word mixes Roman and Devanagari letters: "Kaटोरा"' in problems


@pytest.mark.parametrize("text", ["Munni ने 5 पत्ते गिने", "Farsh par katora", "फ़र्श पर", "🙂 ok"])
def test_words_in_one_script_each_are_fine(text: str) -> None:
    assert RegisterDetector.mixed_script_words(text) == []


ROMAN_WORD = st.text(alphabet=st.characters(min_codepoint=0x61, max_codepoint=0x7A), min_size=1)
DEVANAGARI_WORD = st.text(
    alphabet=st.characters(min_codepoint=0x0915, max_codepoint=0x0939), min_size=1
)


@given(words=st.lists(st.one_of(ROMAN_WORD, DEVANAGARI_WORD), max_size=8))
def test_a_sentence_of_single_script_words_never_has_a_mixed_word(words: list[str]) -> None:
    assert RegisterDetector.mixed_script_words(" ".join(words)) == []


@given(roman=ROMAN_WORD, devanagari=DEVANAGARI_WORD)
def test_any_word_joining_both_scripts_is_found(roman: str, devanagari: str) -> None:
    assert RegisterDetector.mixed_script_words(f"aaj {roman}{devanagari} hai") == [
        roman + devanagari
    ]
