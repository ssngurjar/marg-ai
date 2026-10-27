"""LlamaGuardOutputParser: Llama Guard's answer read strictly (s07 §4.3)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.errors import ProviderResponseInvalid
from app.domain.enums import SafetyCategory
from app.providers.safety.llama_guard_output_parser import LlamaGuardOutputParser

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("raw", ["safe", "  safe\n", "\nsafe"])
def test_safe_flags_nothing(raw: str) -> None:
    assert LlamaGuardOutputParser.parse(raw) == []


@pytest.mark.parametrize(
    ("raw", "categories"),
    [
        ("unsafe\nS11", [SafetyCategory.SELF_HARM]),
        ("unsafe\nS1,S10", [SafetyCategory.VIOLENT_CRIMES, SafetyCategory.HATE]),
        ("unsafe\nS4, S12", [SafetyCategory.CHILD_EXPLOITATION, SafetyCategory.SEXUAL_CONTENT]),
        (" unsafe\nS14 ", [SafetyCategory.CODE_INTERPRETER_ABUSE]),
    ],
)
def test_unsafe_lists_the_flagged_categories_in_order(
    raw: str, categories: list[SafetyCategory]
) -> None:
    assert LlamaGuardOutputParser.parse(raw) == categories


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "Safe",
        "SAFE",
        "safe.",
        "probably safe",
        "unsafe",  # no codes
        "unsafe\n",
        "unsafe S1",  # no newline
        "unsafe\ns1",  # lower case code
        "unsafe\nS1;S2",
        "unsafe\nS1,",
        "unsafe\nO1",  # Llama Guard 3 style
        "I can't help with that.",
        "safe\nunsafe\nS1",
    ],
)
def test_anything_else_is_an_invalid_response_never_a_guess(raw: str) -> None:
    with pytest.raises(ProviderResponseInvalid, match="isn't 'safe' or 'unsafe'"):
        LlamaGuardOutputParser.parse(raw)


@pytest.mark.parametrize("code", ["S0", "S15", "S99"])
def test_a_code_outside_s1_to_s14_is_invalid(code: str) -> None:
    with pytest.raises(ProviderResponseInvalid, match=f"unknown category {code}"):
        LlamaGuardOutputParser.parse(f"unsafe\n{code}")


@given(numbers=st.lists(st.integers(min_value=1, max_value=14), min_size=1, max_size=5))
def test_every_listed_code_in_range_is_returned(numbers: list[int]) -> None:
    raw = "unsafe\n" + ",".join(f"S{number}" for number in numbers)
    assert LlamaGuardOutputParser.parse(raw) == [SafetyCategory(f"s{n}") for n in numbers]
