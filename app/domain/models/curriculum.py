"""The textbook chapter catalogue (s10 §4.5): official NCERT titles, used only as a hint."""

from datetime import date
from typing import Literal

from pydantic import Field, HttpUrl

from app.domain.models.base import DomainModel

type Subject = Literal["science", "mathematics", "social_science"]


class Chapter(DomainModel):
    number: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=120)


class CatalogueBook(DomainModel):
    book: str = Field(min_length=1, max_length=120)  # exactly as printed on the official page
    grade: int = Field(ge=1, le=12)
    subject: Subject
    medium: Literal["english", "hindi"]
    edition: str = Field(min_length=1, max_length=20)
    source_url: HttpUrl
    retrieved_on: date
    chapters: list[Chapter] = Field(min_length=1)


class ChapterMatch(DomainModel):
    book: CatalogueBook
    chapter: Chapter
    score: float

    @property
    def hint(self) -> str:
        subject = self.book.subject.replace("_", " ")
        return f"{self.chapter.title} (Class {self.book.grade} {subject}, NCERT {self.book.book})"
