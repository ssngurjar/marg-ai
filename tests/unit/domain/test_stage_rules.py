"""StageRules: age band from birth year (s10b §4.2; CLAUDE.md §3 domain/stages)."""

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.errors import InvalidProfileValue
from app.domain.enums import AgeBand
from app.domain.rules.stage_rules import StageRules

pytestmark = pytest.mark.unit

TODAY = date(2026, 10, 27)


@pytest.mark.parametrize(
    ("age", "band"),
    [
        (0, AgeBand.UNDER_3), (2, AgeBand.UNDER_3), (3, AgeBand.FOUNDATIONAL_3_8),
        (8, AgeBand.FOUNDATIONAL_3_8), (9, AgeBand.PREPARATORY_8_11),
        (10, AgeBand.PREPARATORY_8_11), (11, AgeBand.MIDDLE_11_14), (13, AgeBand.MIDDLE_11_14),
        (14, AgeBand.SECONDARY_14_18), (17, AgeBand.SECONDARY_14_18), (18, AgeBand.ADULT),
    ],
)  # fmt: skip
def test_band_boundaries_are_exact(age: int, band: AgeBand) -> None:
    assert StageRules.age_band(TODAY.year - age, TODAY) is band


def test_a_future_birth_year_is_refused() -> None:
    with pytest.raises(InvalidProfileValue, match="birth_year 2027 is in the future"):
        StageRules.age_band(2027, TODAY)


@given(birth_year=st.integers(min_value=1900, max_value=TODAY.year))
def test_every_valid_birth_year_has_exactly_one_band(birth_year: int) -> None:
    band = StageRules.age_band(birth_year, TODAY)
    assert band in set(AgeBand)
    assert StageRules.age_on(birth_year, TODAY) == TODAY.year - birth_year


@given(older=st.integers(1900, TODAY.year), younger=st.integers(1900, TODAY.year))
def test_older_children_never_get_an_earlier_band(older: int, younger: int) -> None:
    order = list(AgeBand)
    if older <= younger:
        assert order.index(StageRules.age_band(older, TODAY)) >= order.index(
            StageRules.age_band(younger, TODAY)
        )
