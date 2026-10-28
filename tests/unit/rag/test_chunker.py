"""Chunker: heading-aware, token-budgeted, deterministic (s11 §4.3; CLAUDE.md §3 properties)."""

import itertools
import re

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from app.rag.chunker import ChunkDraft, Chunker

pytestmark = pytest.mark.unit

TITLE = "NMMS scholarship — eligibility"
WORDS = st.sampled_from(
    [
        "scholarship", "class", "8", "₹12,000", "NMMS", "छात्रवृत्ति", "कक्षा", "क्षेत्र",
        "पढ़ाई", "padhai", "bachche", "form", "bharna", "🙂", "🙋🏽", "exam.", "हाँ।", "kyun?",
        "apply!", "स्कॉलरशिप", "\n", "\n\n",
    ]
)  # fmt: skip
SENTENCES = st.lists(WORDS, min_size=1, max_size=400).map(" ".join)
LONG_RUNS = st.text(alphabet="कखगक्षा्ि", min_size=400, max_size=1600)  # no whitespace at all


@st.composite
def bodies(draw: st.DrawFn) -> str:
    sections = draw(st.lists(st.tuples(st.booleans(), SENTENCES), min_size=1, max_size=5))
    lines: list[str] = []
    for position, (subsection, text) in enumerate(sections):
        level = "###" if subsection and position else "##"
        lines.extend([f"{level} Part {position}", text])
    return "\n".join(lines)


def non_whitespace(text: str) -> str:
    return re.sub(r"\s+", "", text)


def section_texts(body: str) -> str:
    """The body without its heading lines: what the chunks must carry."""
    return "".join(line for line in body.splitlines() if not Chunker.HEADING.match(line))


def carried(drafts: list[ChunkDraft]) -> str:
    return "".join(draft.body[draft.overlap_chars :] for draft in drafts)


@given(bodies())
@settings(max_examples=150)
@example("## Who can apply\n" + "क्षत्रिय " * 300)
def test_chunks_cover_the_text_in_order_once_overlaps_are_removed(body: str) -> None:
    drafts = Chunker.chunk(TITLE, body)
    assert non_whitespace(carried(drafts)) == non_whitespace(section_texts(body))


@given(bodies())
@settings(max_examples=150)
def test_no_chunk_is_over_budget_or_empty(body: str) -> None:
    for draft in Chunker.chunk(TITLE, body):
        assert Chunker.approx_tokens(draft.body) <= Chunker.MAX_TOKENS
        assert draft.body.strip()


@given(bodies())
@settings(max_examples=100)
def test_overlap_is_bounded_and_really_repeats_the_previous_chunk(body: str) -> None:
    drafts = Chunker.chunk(TITLE, body)
    for previous, current in itertools.pairwise(drafts):
        if current.overlap_chars and previous.heading_path == current.heading_path:
            repeated = current.body[: current.overlap_chars].strip()
            assert Chunker.approx_tokens(repeated) <= Chunker.OVERLAP_TOKENS
            assert previous.body.endswith(repeated)


@given(bodies())
@settings(max_examples=50)
def test_chunking_is_deterministic(body: str) -> None:
    assert Chunker.chunk(TITLE, body) == Chunker.chunk(TITLE, body)


@given(LONG_RUNS)
@settings(max_examples=50)
@example("ा" + "क" * 500)  # found by Hypothesis: a run that itself starts with a vowel sign
def test_a_run_without_spaces_is_cut_but_never_inside_a_letter(run: str) -> None:
    drafts = Chunker.chunk(TITLE, f"## Long\n{run}")
    assert non_whitespace(carried(drafts)) == run
    for draft in drafts:
        assert Chunker.approx_tokens(draft.body) <= Chunker.MAX_TOKENS
    for draft in drafts[1:]:  # a cut never leaves a vowel sign or virama at the start
        assert not draft.body[draft.overlap_chars :].startswith(("्", "ि", "ा"))


def test_a_short_section_is_one_chunk_with_the_title_and_heading_in_front() -> None:
    [draft] = Chunker.chunk(TITLE, "## Who can apply\nStudents of class 8 in government schools.")
    assert draft.heading_path == "Who can apply"
    assert draft.text == f"{TITLE} — Who can apply\n\nStudents of class 8 in government schools."
    assert (draft.position, draft.overlap_chars) == (0, 0)


def test_a_subheading_keeps_its_parent_in_the_path() -> None:
    drafts = Chunker.chunk(TITLE, "## How to apply\nOnline.\n### Documents\nIncome certificate.")
    assert [draft.heading_path for draft in drafts] == ["How to apply", "How to apply > Documents"]


def test_a_heading_with_nothing_under_it_makes_no_chunk() -> None:
    drafts = Chunker.chunk(TITLE, "## Empty\n## Full\nText here.")
    assert [draft.heading_path for draft in drafts] == ["Full"]


def test_the_danda_ends_a_sentence() -> None:
    sentence = "यह योजना कक्षा 8 के छात्रों के लिए है। "
    drafts = Chunker.chunk(TITLE, "## Hindi\n" + sentence * 80)
    assert len(drafts) > 1
    assert all(draft.body.endswith("।") for draft in drafts)


def test_tokens_are_utf8_bytes_over_four_rounded_up() -> None:
    assert Chunker.approx_tokens("") == 0
    assert Chunker.approx_tokens("abcd") == 1
    assert Chunker.approx_tokens("abcde") == 2
    assert Chunker.approx_tokens("क") == 1  # 3 bytes
