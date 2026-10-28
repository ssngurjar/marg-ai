"""ChapterCatalogue: the NCERT chapter titles, validated at startup (s10 §4.5).

An invalid entry stops the process, naming the book and grade. An empty catalogue is valid: the
exposure layer then bridges from the teacher's own words.
"""

from pathlib import Path
from typing import Final

import yaml
from pydantic import ValidationError

from app.core.errors import CorpusValidationError
from app.domain.models.curriculum import CatalogueBook

CATALOGUE_FILE: Final = (
    Path(__file__).resolve().parents[2] / "corpus" / "curriculum" / "ncert_chapters.yaml"
)


class ChapterCatalogue:
    def __init__(self, books: tuple[CatalogueBook, ...]) -> None:
        self.books = books

    @staticmethod
    def load(path: Path = CATALOGUE_FILE) -> "ChapterCatalogue":
        loaded: object = yaml.safe_load(path.read_text(encoding="utf-8"))
        if loaded is None:
            return ChapterCatalogue(())
        if not isinstance(loaded, list):
            raise CorpusValidationError(f"{path.name}: expected a list of books")
        books: list[CatalogueBook] = []
        seen: set[tuple[int, str, str, int]] = set()
        for position, entry in enumerate(loaded, start=1):
            try:
                book = CatalogueBook.model_validate(entry)
            except ValidationError as exc:
                raise CorpusValidationError(f"{path.name}: entry {position}: {exc}") from exc
            for chapter in book.chapters:
                key = (book.grade, book.subject, book.medium, chapter.number)
                if key in seen:
                    raise CorpusValidationError(
                        f"{path.name}: {book.book} grade {book.grade}: chapter {chapter.number} "
                        "appears twice"
                    )
                seen.add(key)
            books.append(book)
        return ChapterCatalogue(tuple(books))
