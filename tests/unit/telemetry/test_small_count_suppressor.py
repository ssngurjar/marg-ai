"""SmallCountSuppressor: the k-anonymity floor (s13 §4.7)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.telemetry.small_count_suppressor import SmallCountSuppressor

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("value", "shown"), [(0, None), (4, None), (5, 5), (6, 6)])
def test_the_floor_of_five_hides_four_and_shows_five(value: int, shown: int | None) -> None:
    assert SmallCountSuppressor.count(value, 5) == shown


def test_the_admin_floor_of_one_hides_only_zero() -> None:
    assert SmallCountSuppressor.count(0, 1) is None
    assert SmallCountSuppressor.count(1, 1) == 1


@given(
    st.dictionaries(st.text(max_size=8), st.integers(min_value=0, max_value=50)), st.integers(1, 10)
)
def test_every_count_is_either_itself_or_hidden_and_hidden_exactly_below_the_floor(
    counts: dict[str, int], floor: int
) -> None:
    shown = SmallCountSuppressor.counts(counts, floor)
    assert shown.keys() == counts.keys()
    for key, value in counts.items():
        assert shown[key] == (value if value >= floor else None)
