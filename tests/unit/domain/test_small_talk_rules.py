"""An "ok", thanks, emoji or good night is small talk, answered at once (owner's field test)."""

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from app.domain.rules.small_talk_rules import SmallTalkRules

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "text",
    ["okay okay", "okk okk 🤣", "🥰", "👍👍", "thank you", "achha theek hai", "Ok", "हाँ जी", "hmm"],
)
def test_acknowledgements_thanks_and_emoji_are_small_talk(text: str) -> None:
    assert SmallTalkRules.kind(text) == "thanks"


@pytest.mark.parametrize("text", ["acha good night", "good night", "bye", "Shubh ratri", "gn"])
def test_a_goodbye_is_good_night(text: str) -> None:
    assert SmallTalkRules.kind(text) == "good_night"


@pytest.mark.parametrize(
    "text",
    [
        "kya main neet nikaal sakti hoon", "tum mujhse pyaar karte ho kya", "mujhe achha lagega",
        "sticker bhej kar", "ok but how do I become a nurse", "", "   ", "12345",
    ],
)  # fmt: skip
def test_anything_with_a_question_or_a_thought_is_not(text: str) -> None:
    assert SmallTalkRules.kind(text) is None


@given(words=st.lists(st.sampled_from(["nurse", "kaise", "UPSC", "padhai", "kab"]), min_size=1))
@example(words=["ok", "nurse"])
def test_a_message_with_any_real_word_is_never_small_talk(words: list[str]) -> None:
    assert SmallTalkRules.kind(" ".join(["ok", *words])) is None
