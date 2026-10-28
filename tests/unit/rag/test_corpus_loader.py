"""CorpusLoader: every corpus file validated before ingestion (s11 §4.1)."""

from datetime import date
from pathlib import Path

import pytest

from app.core.errors import CorpusValidationError
from app.domain.enums import CorpusTopic
from app.rag.corpus_loader import CorpusLoader

pytestmark = pytest.mark.unit

TODAY = date(2026, 10, 28)
GOOD_FRONTMATTER = {
    "title": "NMMS scholarship — who can apply",
    "source_url": "https://www.myscheme.gov.in/schemes/nmmss",
    "retrieved_on": "2026-10-28",
    "topic": "scholarships",
    "grades": "[8]",
    "keywords": "[NMMS, scholarship]",
    "language": "english",
}
GOOD_BODY = "## Who can apply\nStudents of class 8.\n"


def document(body: str = GOOD_BODY, **changes: str | None) -> bytes:
    fields: dict[str, str | None] = {**GOOD_FRONTMATTER, **changes}
    lines = [f"{key}: {value}" for key, value in fields.items() if value is not None]
    return ("---\n" + "\n".join(lines) + "\n---\n" + body).encode()


def parse(content: bytes, path: str = "corpus/scholarships/nmms.md") -> object:
    return CorpusLoader.parse(path, content, TODAY)


def test_a_good_file_parses_with_its_hash() -> None:
    parsed = CorpusLoader.parse("corpus/scholarships/nmms.md", document(), TODAY)
    assert parsed.frontmatter.topic is CorpusTopic.SCHOLARSHIPS
    assert parsed.frontmatter.grades == [8]
    assert parsed.body == GOOD_BODY.strip()
    assert len(parsed.content_sha256) == 64


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"source_url": None}, "source_url"),
        ({"retrieved_on": None}, "retrieved_on"),
        ({"source_url": "http://scholarships.gov.in"}, "must be https"),
        ({"retrieved_on": "2026-10-29"}, "in the future"),
        ({"retrieved_on": "2025-10-27"}, "over a year old"),
        ({"topic": "exams"}, "must equal its folder"),
        ({"topic": "cooking"}, "topic"),
        ({"grades": "[13]"}, "grades"),
        ({"grades": "[0]"}, "grades"),
        ({"keywords": "['  ']"}, "keywords"),
        ({"keywords": "[]"}, "keywords"),
        ({"title": "abc"}, "title"),
        ({"price": "10"}, "price"),
    ],
    ids=[
        "no_url", "no_date", "http", "future", "stale", "wrong_folder", "unknown_topic",
        "grade_13", "grade_0", "blank_keyword", "no_keywords", "short_title", "unknown_key",
    ],
)  # fmt: skip
def test_each_rule_names_the_file_and_the_problem(
    changes: dict[str, str | None], message: str
) -> None:
    with pytest.raises(CorpusValidationError, match=message) as raised:
        parse(document(GOOD_BODY, **changes))
    assert "corpus/scholarships/nmms.md" in str(raised.value)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("", "body is empty"),
        ("Just text, no heading.", "## heading"),
        ("## Apply\n<script>alert(1)</script>", "raw HTML"),
    ],
)
def test_a_bad_body_is_refused(body: str, message: str) -> None:
    with pytest.raises(CorpusValidationError, match=message):
        parse(document(body=body))


@pytest.mark.parametrize(
    "content", [b"no frontmatter at all", b"---\n: : :\n---\n## A\nb", b"\xff\xfe\x00"]
)
def test_unreadable_files_are_refused(content: bytes) -> None:
    with pytest.raises(CorpusValidationError):
        parse(content)


def test_loading_lists_every_bad_file_and_skips_what_isnt_corpus(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    (root / "scholarships").mkdir(parents=True)
    (root / "exams").mkdir()
    (root / "curriculum").mkdir()
    (root / "SOURCES.md").write_text("# not corpus")
    (root / "curriculum" / "class6.md").write_text("not corpus either")
    (root / "scholarships" / "good.md").write_bytes(document())
    (root / "scholarships" / "bad.md").write_bytes(document(source_url=None))
    (root / "exams" / "worse.md").write_bytes(document())  # topic scholarships in exams/
    with pytest.raises(CorpusValidationError) as raised:
        CorpusLoader.load(TODAY, root)
    message = str(raised.value)
    assert "corpus/scholarships/bad.md" in message
    assert "corpus/exams/worse.md" in message
    assert "good.md" not in message
    assert "SOURCES" not in message
    assert "class6" not in message


def test_a_valid_corpus_loads_sorted(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    (root / "scholarships").mkdir(parents=True)
    (root / "scholarships" / "b.md").write_bytes(document())
    (root / "scholarships" / "a.md").write_bytes(document())
    loaded = CorpusLoader.load(TODAY, root)
    assert [corpus_file.path for corpus_file in loaded] == [
        "corpus/scholarships/a.md",
        "corpus/scholarships/b.md",
    ]
