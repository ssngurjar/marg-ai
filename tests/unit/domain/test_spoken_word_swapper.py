"""SpokenWordSwapper with the reviewed swaps: whole words only, meaning kept, idempotent."""

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from app.constants.spoken_words import SPOKEN_WORD_SWAPS
from app.domain.rules.spoken_word_swapper import SpokenWordSwapper

pytestmark = pytest.mark.unit


def spoken(text: str) -> str:
    return SpokenWordSwapper.swap(text, SPOKEN_WORD_SWAPS)


@pytest.mark.parametrize(
    ("written", "said"),
    [
        ("पूछिए आज क्या पढ़ा।", "पूछ लीजिए आज क्या पढ़ा।"),  # owner's listening test
        ("रोज़ पास बिठाइए।", "रोज़ पास बैठाइए।"),
        ("आज शाम पूछिए, क्या अच्छा लगा?", "आज शाम पूछ लीजिए, क्या अच्छा लगा?"),
        ("पूछिये और बिठाइये", "पूछ लीजिए और बैठाइए"),
    ],
)
def test_words_the_voice_says_badly_are_swapped(written: str, said: str) -> None:
    assert spoken(written) == said


@pytest.mark.parametrize(
    "text",
    [
        "पूछिएगा आज",  # a longer word that only starts the same
        "आप पूछ लीजिए",  # already the spoken form
        "उसे बैठाइए",
        "Poochhiye aaj kya padha",  # Roman script is never spoken by the Hindi voice
        "",
    ],
)
def test_other_words_are_left_alone(text: str) -> None:
    assert spoken(text) == text


PIECES = [*"पूछिएबठाइये लीजआ ,।", "पूछिए", "बिठाइए", "पूछ लीजिए", "बैठाइए"]


@given(st.lists(st.sampled_from(PIECES), max_size=30).map("".join))
@example("पूछिएपूछिए")
def test_swapping_is_idempotent(text: str) -> None:
    once = spoken(text)
    assert spoken(once) == once


@pytest.mark.parametrize("end", ["।", "॥", "?", "!", ",", " ", ""])
def test_a_word_before_any_punctuation_is_still_swapped(end: str) -> None:
    # regression: the danda is in the Devanagari block and hid the word's end
    assert spoken(f"पूछिए{end}") == f"पूछ लीजिए{end}"
