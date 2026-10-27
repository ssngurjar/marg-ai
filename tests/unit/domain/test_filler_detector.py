"""FillerDetector: only sounds count as nothing said (s06 §8)."""

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from app.domain.rules.filler_detector import FillerDetector

pytestmark = pytest.mark.unit

SOUNDS = st.sampled_from(sorted(FillerDetector.FILLER_SOUNDS))
GAPS = st.sampled_from([" ", "... ", ", ", "! ", "\n", "  "])


@pytest.mark.parametrize(
    "transcript", ["", "   ", "umm", "Umm...", "hmm, uh", "हम्म", "उम्म अं", "MMM!"]
)
def test_sounds_alone_are_nothing_said(transcript: str) -> None:
    assert FillerDetector.is_only_filler(transcript)


@pytest.mark.parametrize(
    "transcript",
    ["haan", "nahi", "accha", "ok", "हाँ", "umm haan", "hmm, beta khana nahi khata", "12", "🙂 3"],
)
def test_a_word_that_answers_something_is_not_filler(transcript: str) -> None:
    assert not FillerDetector.is_only_filler(transcript)


@given(sounds=st.lists(SOUNDS, max_size=6), gaps=st.lists(GAPS, min_size=6, max_size=6))
def test_any_run_of_sounds_is_filler(sounds: list[str], gaps: list[str]) -> None:
    transcript = "".join(f"{sound}{gap}" for sound, gap in zip(sounds, gaps, strict=False))
    assert FillerDetector.is_only_filler(transcript)


@given(
    sounds=st.lists(SOUNDS, max_size=4),
    word=st.sampled_from(["haan", "beta", "khoj", "बच्चा", "nahi", "Munni"]),
)
@example(sounds=["umm"], word="haan")
def test_one_real_word_among_sounds_makes_it_speech(sounds: list[str], word: str) -> None:
    assert not FillerDetector.is_only_filler(" ".join([*sounds, word, *sounds]))
