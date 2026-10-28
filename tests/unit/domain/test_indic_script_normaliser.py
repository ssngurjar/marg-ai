"""IndicScriptNormaliser: Hindi heard in another Indian script goes back to Devanagari; nothing
else changes (owner, 2026-10-28)."""

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from app.domain.rules.indic_script_normaliser import IndicScriptNormaliser

pytestmark = pytest.mark.unit

to_devanagari = IndicScriptNormaliser.to_devanagari


@pytest.mark.parametrize(
    ("heard", "meant"),
    [
        ("મેરો ચોરા સ્કૂલ નાઈ રહ્યો આ", "मेरो चोरा स्कूल नाई रह्यो आ"),  # Gujarati, the real slip
        ("ਮੇਰਾ ਬੇਟਾ", "मेरा बेटा"),  # Gurmukhi
        ("আমি", "आमि"),  # Bengali letters, mapped letter by letter
    ],
)
def test_other_indian_scripts_become_devanagari(heard: str, meant: str) -> None:
    assert to_devanagari(heard) == meant


NOT_TOUCHED = st.text(
    alphabet=st.characters(
        categories=("L", "M", "N", "P", "Zs", "So"),
        exclude_characters="".join(
            chr(code) for code in range(0x0980, 0x0B80)
        ),  # the four mapped blocks
    ),
    max_size=80,
)


@given(NOT_TOUCHED)
@example("मेरो लाला मोबाइल देखतो है 😊")
@example("Mero lala, kya haal hai? 123")
def test_devanagari_roman_digits_and_emoji_are_left_alone(text: str) -> None:
    assert to_devanagari(text) == text


@given(st.text(max_size=80))
@example("મેરો ચોરા")
def test_it_keeps_every_letter_and_is_idempotent(text: str) -> None:
    once = to_devanagari(text)
    assert len(once) == len(text)
    assert to_devanagari(once) == once


@given(st.text(alphabet=st.characters(min_codepoint=0x0A80, max_codepoint=0x0AFF), min_size=1))
def test_nothing_from_gujarati_is_left(text: str) -> None:
    assert not any(0x0A80 <= ord(letter) <= 0x0AFF for letter in to_devanagari(text))
