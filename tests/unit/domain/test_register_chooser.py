"""RegisterChooser: a few words don't change the family's language (owner, 2026-10-28)."""

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from app.domain.enums import Language
from app.domain.rules.register_chooser import RegisterChooser
from app.domain.rules.register_detector import RegisterDetector

pytestmark = pytest.mark.unit

H, HI, E = Language.HINGLISH, Language.HINDI, Language.ENGLISH


@pytest.mark.parametrize("message", ["ok", "bye", "haan ji", "Main Munni hoon", "thank you", "👍"])
def test_a_short_roman_message_keeps_a_hinglish_family_in_hinglish(message: str) -> None:
    assert RegisterChooser.choose(message, H) is H


@pytest.mark.parametrize("message", ["ok", "thanks", "yes please"])
def test_a_short_roman_message_keeps_a_hindi_family_in_hindi(message: str) -> None:
    assert RegisterChooser.choose(message, HI) is HI


@pytest.mark.parametrize("message", ["हाँ", "ठीक है", "मुन्नी"])
def test_devanagari_means_hindi_however_short(message: str) -> None:
    assert RegisterChooser.choose(message, H) is HI


def test_four_words_in_another_language_switch() -> None:
    assert RegisterChooser.choose("Can you please explain this", H) is E
    assert RegisterChooser.choose("Mujhe aaj ki khoj batao", E) is H


def test_with_no_known_language_the_message_decides() -> None:
    assert RegisterChooser.choose("bye", None) is RegisterDetector.detect("bye")
    assert RegisterChooser.choose("", None) is None


def test_an_empty_message_keeps_the_family_language() -> None:
    assert RegisterChooser.choose("", H) is H


ROMAN_WORD = st.text(
    alphabet=st.sampled_from(list("abcdefghijklmnopqrstuvwxyz")), min_size=1, max_size=8
)
DEVANAGARI_WORD = st.text(
    alphabet=st.sampled_from(list("कखगचजटडतदनपबमयरलवसह")), min_size=1, max_size=6
)
LANGUAGES = st.sampled_from(list(Language))


@given(st.lists(ROMAN_WORD, min_size=1, max_size=RegisterChooser.MIN_WORDS - 1), LANGUAGES)
@example(["main", "munni", "hoon"], H)
def test_fewer_than_four_roman_words_never_move_a_known_language(
    words: list[str], usual: Language
) -> None:
    assert RegisterChooser.choose(" ".join(words), usual) is usual


@given(st.lists(DEVANAGARI_WORD, min_size=1, max_size=6), LANGUAGES)
def test_devanagari_words_always_mean_hindi(words: list[str], usual: Language) -> None:
    assert RegisterChooser.choose(" ".join(words), usual) is HI


@given(st.text(max_size=60), LANGUAGES)
@example("😊🙏", H)
def test_the_answer_is_always_the_family_language_or_what_was_written(
    text: str, usual: Language
) -> None:
    assert RegisterChooser.choose(text, usual) in {usual, RegisterDetector.detect(text)}
