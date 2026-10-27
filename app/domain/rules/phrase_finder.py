"""PhraseFinder: whole-phrase matching on normalised text, for keyword rules (s07, s08). Pure.

Text and phrases are normalised the same way: NFC, casefold, Devanagari nukta and nasal marks
dropped (ख़ुदकुशी = खुदकुशी, नहीं = नही), anything but letters, marks and digits turned into
spaces, spaces collapsed. A phrase matches as a whole-word sequence, so "die" never matches
"diesel".
"""

import unicodedata
from collections.abc import Iterable, Sequence
from typing import ClassVar


class PhraseFinder:
    _DROPPED_MARKS: ClassVar[frozenset[str]] = frozenset(
        {
            "़",  # nukta
            "ँ",  # chandrabindu
            "ं",  # anusvara
        }
    )

    @staticmethod
    def normalise(text: str) -> str:
        decomposed = unicodedata.normalize("NFD", text.casefold())
        kept: list[str] = []
        for character in decomposed:
            if character in PhraseFinder._DROPPED_MARKS:
                continue
            category = unicodedata.category(character)
            kept.append(character if category[0] in {"L", "M", "N"} else " ")
        return " ".join(unicodedata.normalize("NFC", "".join(kept)).split())

    @staticmethod
    def words(text: str) -> list[str]:
        return PhraseFinder.normalise(text).split()

    @staticmethod
    def positions(words: Sequence[str], phrase: str) -> list[int]:
        """Where `phrase` starts in `words` (already normalised), as a whole-word sequence."""
        phrase_words = PhraseFinder.words(phrase)
        if not phrase_words:
            return []
        span = len(phrase_words)
        return [
            start
            for start in range(len(words) - span + 1)
            if list(words[start : start + span]) == phrase_words
        ]

    @staticmethod
    def contains_any(text: str, phrases: Iterable[str]) -> bool:
        words = PhraseFinder.words(text)
        return any(PhraseFinder.positions(words, phrase) for phrase in phrases)

    @staticmethod
    def is_exactly(text: str, phrases: Iterable[str]) -> bool:
        """The whole message is one of the phrases (after normalising)."""
        normalised = PhraseFinder.normalise(text)
        return any(normalised == PhraseFinder.normalise(phrase) for phrase in phrases)
