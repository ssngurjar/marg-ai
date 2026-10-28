"""ChapterMatcher: which official chapter a teacher means, if any (s10 §4.5). Pure, deterministic.

The share of a chapter title's words found in the message; the best score of at least 0.6 wins,
and a tie is no match. Only the teacher's grade and subject are searched. A miss is normal (a
state-board book, a topic outside the syllabus, a misheard title): the teacher's own words are
used instead, never refused.
"""

from collections.abc import Sequence
from typing import ClassVar, Final

from app.domain.models.curriculum import CatalogueBook, ChapterMatch, Subject
from app.domain.rules.phrase_finder import PhraseFinder

SUBJECT_WORDS: Final[dict[str, Subject]] = {
    "science": "science", "vigyan": "science", "विज्ञान": "science",
    "maths": "mathematics", "math": "mathematics", "mathematics": "mathematics",
    "ganit": "mathematics", "गणित": "mathematics",
    "social science": "social_science", "sst": "social_science", "samajik vigyan": "social_science",
    "सामाजिक विज्ञान": "social_science", "history": "social_science", "geography": "social_science",
    "civics": "social_science",
}  # fmt: skip
"""What onboarding stored as the subject → the catalogue's key. Unmapped: no lookup."""


class ChapterMatcher:
    MIN_SCORE: ClassVar[float] = 0.6

    @staticmethod
    def subject_of(stored: str | None) -> Subject | None:
        if not stored:
            return None
        return SUBJECT_WORDS.get(" ".join(PhraseFinder.words(stored)))

    @staticmethod
    def match(
        text: str, grade: int | None, subject: Subject | None, books: Sequence[CatalogueBook]
    ) -> ChapterMatch | None:
        if grade is None or subject is None:
            return None
        said = set(PhraseFinder.words(text))
        best: list[ChapterMatch] = []
        for book in books:
            if book.grade != grade or book.subject != subject:
                continue  # another class or subject: never a match
            for chapter in book.chapters:
                title_words = set(PhraseFinder.words(chapter.title))
                if not title_words:
                    continue  # a title of only marks or punctuation can't be matched
                score = len(title_words & said) / len(title_words)
                if score < ChapterMatcher.MIN_SCORE:
                    continue
                candidate = ChapterMatch(book=book, chapter=chapter, score=score)
                if not best or score > best[0].score:
                    best = [candidate]
                elif score == best[0].score and chapter.title != best[0].chapter.title:
                    best.append(candidate)
        return best[0] if len(best) == 1 else None

    @staticmethod
    def titles_for(
        grade: int | None, subject: Subject | None, books: Sequence[CatalogueBook], limit: int
    ) -> list[str]:
        """Up to `limit` chapter titles for the teacher's class, to offer when nothing matched."""
        titles: list[str] = []
        for book in books:
            if book.grade == grade and book.subject == subject:
                titles.extend(chapter.title for chapter in book.chapters)
        return titles[:limit]
