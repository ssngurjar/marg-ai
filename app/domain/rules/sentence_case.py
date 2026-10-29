"""SentenceCase: a model-written line shown on its own, starting with a capital and ending with
a full stop ("people who study the stars are called astronomers" read as a fragment; owner's
judge walkthrough, 2026-10-29)."""

from typing import ClassVar


class SentenceCase:
    ENDINGS: ClassVar[tuple[str, ...]] = (".", "!", "?", "।", "॥", ")", '"', "'")

    @staticmethod
    def of(text: str) -> str:
        """Idempotent; text without a lowercase first letter (Devanagari, digits) keeps its
        start, and empty text stays empty."""
        line = text.strip()
        if not line:
            return line
        if line[0].islower():
            line = line[0].upper() + line[1:]
        if not line.endswith(SentenceCase.ENDINGS):
            hindi = "\u0900" <= line[-1] <= "\u097f"
            line = f"{line}{'।' if hindi else '.'}"
        return line
