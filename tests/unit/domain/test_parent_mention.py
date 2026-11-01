"""ParentMention: whether a reply to a child already sends them to Mummy and Papa."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.rules.parent_mention import ParentMention

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "text",
    [
        "Tell Mummy and Papa too!",
        "Mummy-Papa ko bhi batana!",
        "मम्मी-पापा को भी बताना!",
        "Ask your parents about it.",
        "Sit with Mummy and Papa and share one happy thing.",
    ],
)
def test_a_reply_naming_both_parents_or_parents_counts(text: str) -> None:
    assert ParentMention.found(text)


@pytest.mark.parametrize(
    "text",
    ["Ask Mummy which leaf is softest.", "Papa ke saath dekho.", "Chaand khud nahi chamakta.", ""],
)
def test_one_parent_alone_or_none_doesnt_count(text: str) -> None:
    assert not ParentMention.found(text)


@given(st.text(max_size=200))
def test_adding_the_line_always_makes_it_found(text: str) -> None:
    assert ParentMention.found(f"{text}\\n\\nTell Mummy and Papa too!")
