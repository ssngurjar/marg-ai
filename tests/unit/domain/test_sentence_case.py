"""SentenceCase: a line shown on its own reads as a sentence."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.rules.sentence_case import SentenceCase

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("written", "shown"),
    [
        (
            "people who study the stars are called astronomers",
            "People who study the stars are called astronomers.",
        ),  # owner's judge walkthrough, 2026-10-29
        ("Farmers watch the sky too!", "Farmers watch the sky too!"),
        ("तारों को देखने वाले खगोलशास्त्री कहलाते हैं", "तारों को देखने वाले खगोलशास्त्री कहलाते हैं।"),
        ("तारे दिखते हैं।", "तारे दिखते हैं।"),
        ("  ", ""),
        ("", ""),
    ],
)
def test_a_line_starts_with_a_capital_and_ends_with_a_stop(written: str, shown: str) -> None:
    assert SentenceCase.of(written) == shown


@given(st.text(alphabet="abc XYZ.!?।तारे", max_size=30))
def test_sentence_case_is_idempotent(text: str) -> None:
    once = SentenceCase.of(text)
    assert SentenceCase.of(once) == once
