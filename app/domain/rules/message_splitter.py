"""MessageSplitter: a reply cut into channel-sized messages (s05 §4.7). Pure.

WhatsApp's text body limit is 4096 characters; the web channel uses the same limit so both
behave the same. A cut prefers natural boundaries, never splits a citation line, and never
breaks a Devanagari conjunct, a vowel sign or an emoji sequence.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import ClassVar, Final

_PARAGRAPH_BREAK: Final = re.compile(r"\n\n")
_SENTENCE_END: Final = re.compile(r"[।?!.](?=\s)")
_LINE_BREAK: Final = re.compile(r"\n")
_WHITESPACE: Final = re.compile(r"\s")
# A sources-block line rendered by s09: "3. Title — https://…". Kept whole in one message.
_SOURCES_LINE: Final = re.compile(r"(?m)^\d+\. .+ — https?://\S+$")

_VIRAMA: Final = "्"
_ZERO_WIDTH_JOINERS: Final = frozenset({"‌", "‍"})
_REGIONAL_INDICATORS: Final = range(0x1F1E6, 0x1F1FF + 1)
_EMOJI_MODIFIERS: Final = range(0x1F3FB, 0x1F3FF + 1)
_TAG_CHARACTERS: Final = range(0xE0020, 0xE007F + 1)


@dataclass(frozen=True, slots=True)
class _Span:
    start: int
    end: int

    def contains_cut(self, position: int) -> bool:
        return self.start < position < self.end


class MessageSplitter:
    TEXT_LIMIT: ClassVar[int] = 4096
    """WhatsApp's text body limit, used for every channel."""

    @staticmethod
    def split(text: str, limit: int = TEXT_LIMIT) -> list[str]:
        """Split `text` into messages of at most `limit` characters, in order.

        Every non-whitespace character is kept, in order; whitespace at the edges of a part is
        dropped. A text of only whitespace gives no parts.
        """
        if limit < 1:
            raise ValueError(f"limit must be at least 1, got {limit}")
        if not text.strip():
            return []
        if len(text) <= limit:
            return [text]
        parts: list[str] = []
        remaining = text.strip()
        while len(remaining) > limit:
            cut = MessageSplitter._choose_cut(remaining, limit)
            head = remaining[:cut].strip()
            if head:
                parts.append(head)
            remaining = remaining[cut:].strip()
        if remaining:
            parts.append(remaining)
        return parts

    @staticmethod
    def _choose_cut(text: str, limit: int) -> int:
        """Where to end the next part: after the best boundary within the first `limit` chars."""
        protected = [_Span(match.start(), match.end()) for match in _SOURCES_LINE.finditer(text)]
        for boundary in (_PARAGRAPH_BREAK, _SENTENCE_END, _LINE_BREAK, _WHITESPACE):
            cut = MessageSplitter._last_boundary_cut(text, limit, boundary, protected)
            if cut is not None:
                return cut
        # A citation line longer than the limit can't stay whole; any whitespace will do.
        cut = MessageSplitter._last_boundary_cut(text, limit, _WHITESPACE, protected=[])
        if cut is not None:
            return cut
        return MessageSplitter._safe_hard_cut(text, limit)

    @staticmethod
    def _last_boundary_cut(
        text: str, limit: int, boundary: re.Pattern[str], protected: list[_Span]
    ) -> int | None:
        """The cut after the last `boundary` match ending within `limit`, outside `protected`."""
        candidates = [match.end() for match in boundary.finditer(text, 0, limit)]
        for cut in reversed(candidates):
            if cut <= 0 or not text[:cut].strip():
                continue
            if any(span.contains_cut(cut) for span in protected):
                continue
            return cut
        return None

    @staticmethod
    def _safe_hard_cut(text: str, limit: int) -> int:
        """For a run of non-whitespace longer than `limit`: the latest cut splitting no grapheme."""
        for cut in range(limit, 0, -1):
            if MessageSplitter._can_cut_between(text[cut - 1], text[cut]):
                return cut
        return limit

    @staticmethod
    def _can_cut_between(before: str, after: str) -> bool:
        if unicodedata.category(after) in {"Mn", "Mc", "Me"}:  # a vowel sign or other mark
            return False
        if _VIRAMA in {before, after}:
            return False
        if before in _ZERO_WIDTH_JOINERS or after in _ZERO_WIDTH_JOINERS:
            return False
        if unicodedata.name(after, "").startswith("VARIATION SELECTOR"):
            return False
        after_code = ord(after)
        if after_code in _EMOJI_MODIFIERS or after_code in _TAG_CHARACTERS:
            return False
        return not (ord(before) in _REGIONAL_INDICATORS and after_code in _REGIONAL_INDICATORS)
