"""Chunker: a corpus document into heading-aware, token-budgeted chunks (s11 §4.3). Pure.

1. Split the body on `##` / `###` headings; each section keeps its heading path.
2. A section within the budget is one chunk.
3. A larger one is cut into sentences (on . ? ! । and line breaks), packed greedily up to the
   budget; each next chunk starts with the previous one's trailing sentences, up to the overlap.
4. A sentence over the budget is cut by MessageSplitter: at whitespace, never inside a grapheme.
The stored text is "{title} — {heading path}" then the body, so a chunk retrieved alone still
says what it's about. Tokens are approximated as UTF-8 bytes / 4 (over-counts Devanagari: the
safe direction). Changing the budgets means re-ingesting everything, so they're constants here.
"""

import math
import re
from dataclasses import dataclass
from typing import ClassVar

from app.domain.rules.message_splitter import MessageSplitter


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    position: int  # 0-based within the document
    heading_path: str  # "Who can apply" or "How to apply > Documents"
    body: str  # the section text this chunk carries
    text: str  # what's stored and embedded: the title and heading path, then the body
    overlap_chars: int  # how many leading characters of `body` repeat the previous chunk


@dataclass(frozen=True, slots=True)
class _Section:
    heading_path: str
    text: str


class Chunker:
    MAX_TOKENS: ClassVar[int] = 350
    OVERLAP_TOKENS: ClassVar[int] = 50
    HEADING: ClassVar[re.Pattern[str]] = re.compile(r"^(#{2,6})\s+(.+?)\s*#*\s*$")
    SENTENCE_END: ClassVar[re.Pattern[str]] = re.compile(r"(?<=[.?!।])\s+|\n+")
    PATH_SEPARATOR: ClassVar[str] = " > "
    TOP_LEVEL: ClassVar[int] = 2  # "##" starts a new path; deeper headings nest one level

    @staticmethod
    def approx_tokens(text: str) -> int:
        return math.ceil(len(text.encode("utf-8")) / 4)

    @staticmethod
    def chunk(title: str, body: str) -> list[ChunkDraft]:
        drafts: list[ChunkDraft] = []
        for section in Chunker._sections(body):
            for piece_body, overlap_chars in Chunker._pack(Chunker._units(section.text)):
                label = section.heading_path or title
                drafts.append(
                    ChunkDraft(
                        position=len(drafts),
                        heading_path=section.heading_path,
                        body=piece_body,
                        text=f"{title} — {label}\n\n{piece_body}",
                        overlap_chars=overlap_chars,
                    )
                )
        return drafts

    @staticmethod
    def _sections(body: str) -> list[_Section]:
        sections: list[_Section] = []
        path: list[str] = []
        lines: list[str] = []

        def close() -> None:
            text = "\n".join(lines).strip()
            if text:
                sections.append(_Section(Chunker.PATH_SEPARATOR.join(path), text))
            lines.clear()

        for line in body.splitlines():
            heading = Chunker.HEADING.match(line)
            if heading is None:
                lines.append(line)
                continue
            close()
            level, name = len(heading.group(1)), heading.group(2)
            path = [name] if level == Chunker.TOP_LEVEL or not path else [path[0], name]
        close()
        return sections

    @staticmethod
    def _units(text: str) -> list[str]:
        """Sentences, each within the budget (an over-long one is cut at whitespace)."""
        units: list[str] = []
        for sentence in Chunker.SENTENCE_END.split(text):
            stripped = sentence.strip()
            if not stripped:
                continue
            if Chunker.approx_tokens(stripped) <= Chunker.MAX_TOKENS:
                units.append(stripped)
            else:
                # At most MAX_TOKENS characters is at most MAX_TOKENS tokens (≤ 4 bytes each).
                units.extend(MessageSplitter.split(stripped, Chunker.MAX_TOKENS))
        return units

    @staticmethod
    def _pack(units: list[str]) -> list[tuple[str, int]]:
        """(body, overlap characters) per chunk, packing units greedily with a trailing overlap."""
        packed: list[tuple[str, int]] = []
        current: list[str] = []
        overlap: list[str] = []
        for unit in units:
            if current and Chunker.approx_tokens(" ".join([*current, unit])) > Chunker.MAX_TOKENS:
                packed.append(Chunker._joined(current, overlap))
                overlap = Chunker._tail(current, unit)
                current = [*overlap, unit]
            else:
                current.append(unit)
        if current:
            packed.append(Chunker._joined(current, overlap))
        return packed

    @staticmethod
    def _tail(previous: list[str], next_unit: str) -> list[str]:
        """The previous chunk's trailing units within the overlap budget, that still leave room
        for the next unit."""
        tail: list[str] = []
        for unit in reversed(previous):
            candidate = [unit, *tail]
            if Chunker.approx_tokens(" ".join(candidate)) > Chunker.OVERLAP_TOKENS:
                break
            tail = candidate
        while tail and Chunker.approx_tokens(" ".join([*tail, next_unit])) > Chunker.MAX_TOKENS:
            tail = tail[1:]
        if len(tail) == len(previous):
            return []  # repeating a whole chunk adds nothing
        return tail

    @staticmethod
    def _joined(units: list[str], overlap: list[str]) -> tuple[str, int]:
        overlap_chars = len(" ".join(overlap)) + 1 if overlap else 0
        return " ".join(units), overlap_chars
