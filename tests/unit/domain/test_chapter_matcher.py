"""ChapterMatcher and ChapterCatalogue: official chapter titles as a hint, never a gate
(s10 §4.5)."""

import json
from datetime import date
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import HttpUrl

from app.core.errors import CorpusValidationError
from app.domain.models.curriculum import CatalogueBook, Chapter, Subject
from app.domain.rules.chapter_matcher import ChapterMatcher
from app.layers.curriculum_catalogue import ChapterCatalogue

pytestmark = pytest.mark.unit


def book(
    grade: int = 8,
    subject: Subject = "science",
    medium: str = "english",
    titles: tuple[str, ...] = ("Force and Pressure", "Friction", "Sound"),
) -> CatalogueBook:
    return CatalogueBook.model_validate(
        {
            "book": "Science", "grade": grade, "subject": subject, "medium": medium,
            "edition": "2024-25", "source_url": HttpUrl("https://ncert.nic.in/textbook.php?hesc1=0-13"),
            "retrieved_on": date(2026, 10, 30),
            "chapters": [{"number": n, "title": title} for n, title in enumerate(titles, start=1)],
        }
    )  # fmt: skip


BOOKS = [
    book(),
    book(medium="hindi", titles=("बल तथा दाब", "घर्षण")),
    book(grade=7, titles=("Heat",)),
]


@pytest.mark.parametrize(
    "text",
    ["Force and Pressure", "kal Force and Pressure padhana hai", "FORCE & PRESSURE chapter"],
)
def test_a_title_inside_the_message_matches(text: str) -> None:
    match = ChapterMatcher.match(text, 8, "science", BOOKS)
    assert match is not None
    assert match.chapter.title == "Force and Pressure"
    assert match.hint == "Force and Pressure (Class 8 science, NCERT Science)"


def test_a_hindi_title_matches_devanagari() -> None:
    match = ChapterMatcher.match("कल बल तथा दाब पढ़ाना है", 8, "science", BOOKS)
    assert match is not None
    assert match.chapter.title == "बल तथा दाब"


@pytest.mark.parametrize(
    ("text", "grade", "subject"),
    [
        ("solar panel gaon mein lage hain", 8, "science"),
        ("Force and Pressure", 7, "science"),
        ("Force and Pressure", 8, "mathematics"),
        ("Force and Pressure", None, "science"),
        ("Force and Pressure", 8, None),
    ],
)
def test_no_match_outside_the_class_subject_or_titles(
    text: str, grade: int | None, subject: Subject | None
) -> None:
    assert ChapterMatcher.match(text, grade, subject, BOOKS) is None


def test_a_tie_between_two_titles_is_no_match() -> None:
    tied = [book(titles=("Light", "Sound"))]
    assert ChapterMatcher.match("light and sound", 8, "science", tied) is None


@pytest.mark.parametrize(
    ("stored", "subject"),
    [
        ("Science", "science"),
        ("ganit", "mathematics"),
        ("गणित", "mathematics"),
        ("SST", "social_science"),
        ("Hindi", None),
        (None, None),
    ],
)
def test_the_stored_subject_maps_to_the_catalogue(
    stored: str | None, subject: Subject | None
) -> None:
    assert ChapterMatcher.subject_of(stored) == subject


@given(st.text(max_size=200))
def test_any_message_never_raises_and_never_crosses_class_or_subject(text: str) -> None:
    match = ChapterMatcher.match(text, 8, "science", BOOKS)
    assert match is None or (match.book.grade, match.book.subject) == (8, "science")


def test_every_title_matches_itself() -> None:
    for catalogue_book in BOOKS:
        for chapter in catalogue_book.chapters:
            match = ChapterMatcher.match(
                chapter.title, catalogue_book.grade, "science", [catalogue_book]
            )
            assert match is not None
            assert match.score == 1.0


def test_titles_are_offered_for_the_teachers_class_only() -> None:
    assert ChapterMatcher.titles_for(8, "science", BOOKS, 3) == [
        "Force and Pressure",
        "Friction",
        "Sound",
    ]
    assert ChapterMatcher.titles_for(9, "science", BOOKS, 3) == []


def test_the_shipped_catalogue_loads(tmp_path: Path) -> None:
    assert isinstance(ChapterCatalogue.load().books, tuple)


GOOD_ENTRY: dict[str, object] = {
    "book": "B", "grade": 8, "subject": "science", "medium": "english", "edition": "x",
    "source_url": "https://ncert.nic.in", "retrieved_on": "2026-10-30",
    "chapters": [{"number": 1, "title": "T"}],
}  # fmt: skip


def catalogue_text(**changes: object) -> str:
    """A one-book catalogue (JSON is valid YAML); a change of None removes that key."""
    entry = {**GOOD_ENTRY, **changes}
    return json.dumps([{key: value for key, value in entry.items() if value is not None}])


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (catalogue_text(grade=13), "grade"),
        (catalogue_text(source_url=None), "source_url"),
        (catalogue_text(chapters=[{"number": 1, "title": ""}]), "title"),
        (
            catalogue_text(chapters=[{"number": 1, "title": "T"}, {"number": 1, "title": "U"}]),
            "B grade 8: chapter 1 appears twice",
        ),
        (json.dumps({"book": "B"}), "expected a list"),
    ],
    ids=["grade_13", "no_source", "empty_title", "duplicate_number", "not_a_list"],
)
def test_an_invalid_catalogue_stops_startup(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "ncert_chapters.yaml"
    path.write_text(text)
    with pytest.raises(CorpusValidationError, match=message):
        ChapterCatalogue.load(path)


def test_chapter_numbers_start_at_one() -> None:
    with pytest.raises(ValueError, match="number"):
        Chapter(number=0, title="Zero")
