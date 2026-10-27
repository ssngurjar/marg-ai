"""MessageSplitter.split (s05 §4.7; CLAUDE.md §3: domain/text splitting properties)."""

import re
import unicodedata

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from app.domain.rules.message_splitter import MessageSplitter

pytestmark = pytest.mark.unit

VIRAMA = "्"
ZWJ = "‍"
NOT_AT_PART_START = re.compile(r"^[ऀ-ॿ]?[्‍‌︀-️]")

# Units that must never be split: Devanagari conjuncts and vowel signs, emoji sequences.
CLUSTERS = [
    "क्ष",  # conjunct: ka + virama + ssa
    "श्री",  # conjunct + vowel sign
    "बच्चे",  # conjunct inside a word
    "पत्ते",
    "नमस्ते",
    "👍🏽",  # emoji + skin-tone modifier
    "👨‍👩‍👧",  # ZWJ family
    "🇮🇳",  # flag: two regional indicators
    "❤️",  # heart + variation selector
]
WORDS = st.sampled_from(
    [*CLUSTERS, "Munni", "parchhai", "suraj", "chalta", "hai", "kya", "doctor", "NEET", "😊"]
)
SEPARATORS = st.sampled_from([" ", "  ", "\n", "\n\n", ". ", "। ", "? ", "! "])


@st.composite
def replies(draw: st.DrawFn) -> str:
    words = draw(st.lists(WORDS, min_size=1, max_size=120))
    separators = draw(st.lists(SEPARATORS, min_size=len(words), max_size=len(words)))
    return "".join(word + separator for word, separator in zip(words, separators, strict=True))


def non_whitespace(text: str) -> str:
    return "".join(character for character in text if not character.isspace())


@given(text=replies(), limit=st.integers(min_value=12, max_value=200))
@example(text="क्ष" * 50, limit=12)
@example(text="👨‍👩‍👧" * 30, limit=12)
def test_parts_fit_keep_every_character_in_order_and_are_never_empty(text: str, limit: int) -> None:
    parts = MessageSplitter.split(text, limit=limit)
    assert all(len(part) <= limit for part in parts)
    assert all(part.strip() for part in parts)
    assert non_whitespace("".join(parts)) == non_whitespace(text)


@given(text=replies(), limit=st.integers(min_value=12, max_value=200))
@example(text="नमस्ते" * 40, limit=12)
@example(text="🇮🇳" * 40, limit=12)
@example(text="👍🏽" * 40, limit=12)
def test_no_part_starts_inside_a_grapheme(text: str, limit: int) -> None:
    for part in MessageSplitter.split(text, limit=limit)[1:]:
        first = part[0]
        assert unicodedata.category(first) not in {"Mn", "Mc", "Me"}, part[:6]
        assert first not in {VIRAMA, ZWJ, "‌"}
        assert not ("︀" <= first <= "️")
        assert not ("\U0001f3fb" <= first <= "\U0001f3ff")


@given(text=replies(), limit=st.integers(min_value=12, max_value=200))
def test_no_part_ends_on_a_joiner(text: str, limit: int) -> None:
    for part in MessageSplitter.split(text, limit=limit)[:-1]:
        assert part[-1] not in {VIRAMA, ZWJ, "‌"}


def test_exactly_the_limit_is_one_part() -> None:
    text = "a" * MessageSplitter.TEXT_LIMIT
    assert MessageSplitter.split(text) == [text]


def test_one_over_the_limit_is_two_parts() -> None:
    text = "word " * 819 + "ab"  # 4097 characters
    assert len(text) == MessageSplitter.TEXT_LIMIT + 1
    parts = MessageSplitter.split(text)
    assert len(parts) == 2
    assert all(len(part) <= MessageSplitter.TEXT_LIMIT for part in parts)


def test_prefers_a_paragraph_break_over_a_sentence_end() -> None:
    text = "Pehla paragraph. Isme do vaakya hain.\n\nDoosra paragraph yahan hai."
    assert MessageSplitter.split(text, limit=50) == [
        "Pehla paragraph. Isme do vaakya hain.",
        "Doosra paragraph yahan hai.",
    ]


def test_cuts_after_a_devanagari_full_stop() -> None:
    text = "बच्चे ने पत्ते इकट्ठे किए। अब हम गिनते हैं कि कितने हैं।"
    parts = MessageSplitter.split(text, limit=30)
    assert parts[0].endswith("।")


def test_a_citation_line_is_never_split() -> None:
    # s09 renders each source on its own line: "n. title — url".
    citation = "1. NMMS scholarship — https://scholarships.gov.in/nmms"
    text = "Yeh rahi jaankari.\n" + citation
    parts = MessageSplitter.split(text, limit=len(citation) + 5)
    assert citation in parts


@pytest.mark.parametrize("text", ["", "   ", "\n\n\t"])
def test_empty_or_blank_text_gives_no_parts(text: str) -> None:
    assert MessageSplitter.split(text) == []


def test_text_within_the_limit_is_returned_unchanged() -> None:
    assert MessageSplitter.split("  Namaste  ") == ["  Namaste  "]


@pytest.mark.parametrize("limit", [0, -1])
def test_a_limit_below_one_is_rejected(limit: int) -> None:
    with pytest.raises(ValueError, match="limit must be at least 1"):
        MessageSplitter.split("text", limit=limit)
