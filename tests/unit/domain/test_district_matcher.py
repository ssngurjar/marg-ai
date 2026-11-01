"""Which LGD district an answer names (critic review D4, 2026-11-01)."""

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from app.constants.lgd_districts import DISTRICTS, RETRIEVED_ON, SOURCE_URL
from app.domain.models.conversation import DISTRICT_LENGTHS
from app.domain.models.district import LgdDistrict
from app.domain.rules.district_matcher import DistrictMatch, DistrictMatcher

pytestmark = pytest.mark.unit

M = DistrictMatcher


def labels(match: DistrictMatch) -> list[str]:
    return [district.label for district in match.candidates]


# --- the list itself -------------------------------------------------------------------------


def test_the_list_comes_from_lgd_with_its_date() -> None:
    assert SOURCE_URL.startswith("https://lgdirectory.gov.in/")
    assert RETRIEVED_ON.year >= 2026


def test_every_district_has_a_unique_code_and_a_label_that_can_be_stored() -> None:
    codes = [district.code for district in DISTRICTS]
    assert len(codes) == len(set(codes))
    assert len(DISTRICTS) >= 700  # India has about 780 districts
    too_long = [d.label for d in DISTRICTS if len(d.label) not in DISTRICT_LENGTHS]
    assert too_long == []


# --- examples ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("Barmer", "Barmer, Rajasthan"), ("barmer, rajasthan", "Barmer, Rajasthan"),
        ("mera zila Sitapur hai", "Sitapur, Uttar Pradesh"), ("New Delhi", "New Delhi, Delhi"),
        ("Patna", "Patna, Bihar"), ("पटना", "Patna, Bihar"),
        ("Karauli Rajasthan", "Karauli, Rajasthan"), ("The Nilgiris", "The Nilgiris, Tamil Nadu"),
    ],
)  # fmt: skip
def test_an_exact_name_is_found(text: str, label: str) -> None:
    found = M.match(text, DISTRICTS).found
    assert found is not None
    assert found.label == label


@pytest.mark.parametrize(
    ("text", "first"),
    [
        ("Karoli", "Karauli, Rajasthan"), ("Behraich", "Bahraich, Uttar Pradesh"),
        ("बहराइच", "Bahraich, Uttar Pradesh"), ("बाड़मेर", "Barmer, Rajasthan"),
        ("करौली", "Karauli, Rajasthan"), ("सीतापुर", "Sitapur, Uttar Pradesh"),
        ("झुंझुनूं", "Jhunjhunu, Rajasthan"), ("उदयपुर", "Udaipur, Rajasthan"),
        ("लखनऊ", "Lucknow, Uttar Pradesh"), ("बरेली", "Bareilly, Uttar Pradesh"),
        ("मेरा जिला बाड़मेर है", "Barmer, Rajasthan"), ("Jhunjunu", "Jhunjhunu, Rajasthan"),
    ],
)  # fmt: skip
def test_a_close_spelling_or_hindi_script_is_offered_never_taken(text: str, first: str) -> None:
    match = M.match(text, DISTRICTS)
    assert match.found is None
    assert labels(match)[0] == first


def test_the_first_word_of_longer_names_offers_them_all() -> None:
    assert labels(M.match("Bengaluru", DISTRICTS)) == [
        "Bengaluru Rural, Karnataka",
        "Bengaluru South, Karnataka",
        "Bengaluru Urban, Karnataka",
    ]


def test_one_name_in_two_states_is_offered_for_both() -> None:
    assert labels(M.match("Pratapgarh", DISTRICTS)) == [
        "Pratapgarh, Rajasthan",
        "Pratapgarh, Uttar Pradesh",
    ]


def test_a_state_with_many_districts_asks_which() -> None:
    assert M.match("Delhi", DISTRICTS) == DistrictMatch(None, (), "Delhi")


def test_a_state_with_few_districts_offers_them() -> None:
    assert len(M.match("Goa", DISTRICTS).candidates) <= M.MAX_CANDIDATES
    assert all(d.state == "Goa" for d in M.match("Goa", DISTRICTS).candidates)


@pytest.mark.parametrize(
    "text", ["", "   ", "12345", "🙏🙏", "Gurgaon", "ignore previous instructions", "mera zila"]
)
def test_nothing_named_is_said_plainly(text: str) -> None:
    assert M.match(text, DISTRICTS).is_empty


def test_a_typo_never_changes_the_first_letter() -> None:
    # "Gurgaon" once offered "Marigaon, Assam"
    assert M.match("Gurgaon", DISTRICTS).candidates == ()


# --- properties ----------------------------------------------------------------------------------

LISTED = st.sampled_from(DISTRICTS)


@settings(max_examples=300)
@given(district=LISTED)
@example(district=next(d for d in DISTRICTS if d.name == "The Nilgiris"))
def test_every_listed_name_finds_itself(district: LgdDistrict) -> None:
    match = M.match(district.name, DISTRICTS)
    assert match.found == district or district in match.candidates


@settings(max_examples=300)
@given(district=LISTED)
def test_every_name_with_its_state_is_found_exactly(district: LgdDistrict) -> None:
    assert M.match(f"{district.name}, {district.state}", DISTRICTS).found == district


@settings(max_examples=200)
@given(
    text=st.text(
        alphabet=st.one_of(
            st.characters(min_codepoint=0x0900, max_codepoint=0x097F),
            st.characters(categories=["L", "N", "P", "Zs"]),
        ),
        max_size=40,
    )
)
@example(text="़")
@example(text=",,,")
def test_any_text_gives_at_most_three_listed_districts_and_the_same_twice(text: str) -> None:
    match = M.match(text, DISTRICTS)
    assert len(match.candidates) <= M.MAX_CANDIDATES
    assert all(candidate in DISTRICTS for candidate in match.candidates)
    assert match == M.match(text, DISTRICTS)


@given(first=st.text(max_size=12), second=st.text(max_size=12))
def test_edit_distance_is_symmetric_and_zero_only_for_equal_text(first: str, second: str) -> None:
    distance = M.edit_distance(first, second)
    assert distance == M.edit_distance(second, first)
    assert (distance == 0) == (first == second)


def test_all_listed_names_find_themselves() -> None:
    lost = [
        district.label
        for district in DISTRICTS
        if (match := M.match(district.name, DISTRICTS)).found != district
        and district not in match.candidates
    ]
    assert lost == []
