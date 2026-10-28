"""SegmentationOutputParser: SAM 3.1's box tokens → a count (spike F). Payload parsing is core
logic (CLAUDE.md §3): properties over generated answers, plus the malformed cases."""

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from app.core.errors import ProviderResponseInvalid
from app.providers.image.segmentation_output_parser import SegmentationOutputParser

pytestmark = pytest.mark.unit


confidences = st.floats(min_value=0, max_value=1, allow_nan=False).map(lambda c: f"{c:.4f}")
coordinates = st.integers(min_value=0, max_value=4096)
boxes = st.builds(
    lambda x, y, c: f"<|box;x={x};y={y};w=10;h=10;c={c}|>", coordinates, coordinates, confidences
)
# Text around the boxes: anything without the token's own markers (Devanagari and emoji too).
filler = st.text(alphabet=st.characters(blacklist_characters="<|>", codec="utf-8"), max_size=40)


@given(st.lists(boxes, max_size=30), filler)
@example(["<|box;x=0;y=0;w=10;h=10;c=1.0000|>"], "पत्ते 🍃")
def test_the_count_is_the_number_of_boxes_whatever_surrounds_them(
    found: list[str], around: str
) -> None:
    answer = around + around.join(found) + around
    assert SegmentationOutputParser.count(answer) == len(found)


@given(filler)
def test_text_without_boxes_counts_zero(answer: str) -> None:
    assert SegmentationOutputParser.count(answer) == 0


@given(st.lists(boxes, min_size=1, max_size=10), st.integers(min_value=0, max_value=9))
def test_cutting_any_box_short_is_refused(found: list[str], position: int) -> None:
    index = position % len(found)
    broken = [*found[:index], found[index][:-2], *found[index + 1 :]]
    with pytest.raises(ProviderResponseInvalid, match="malformed box"):
        SegmentationOutputParser.count("".join(broken))


@pytest.mark.parametrize("confidence", ["high", "1.5", "-0.1", "", "0.9x"])
def test_a_confidence_outside_zero_to_one_is_refused(confidence: str) -> None:
    with pytest.raises(ProviderResponseInvalid, match="malformed confidence"):
        SegmentationOutputParser.count(f"<|box;x=1;c={confidence}|>")


def test_a_box_without_a_confidence_still_counts() -> None:
    assert SegmentationOutputParser.count("<|box;x=1;y=2|><|box;x=3;y=4|>") == 2
