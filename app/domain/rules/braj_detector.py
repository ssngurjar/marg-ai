"""BrajDetector: does this person speak Braj (owner, 2026-10-28)? Pure; the word and district
lists are reviewed constants passed in.

Yes when their own words are Braj: two Braj forms ("mero chhora naay padh rao"), or one in a
Braj district ("mero lala…" in Karauli). One form alone elsewhere isn't enough: "chhora" is said
all over north India. A district alone never is: a family in Karauli writing Hinglish or Hindi
gets Hinglish or Hindi (owner, 2026-10-31).

Voice notes arrive through speech-to-text, which slips (owner's check, 2026-10-28): it doubles a
word ("मेरोमेरो") or runs two together ("ललितक्षु"). So a doubled word counts once as itself,
and a Devanagari form of three or more letters also counts inside a longer word. Roman forms
only match whole words: "toy" inside "story" isn't Braj.
"""

import unicodedata
from collections.abc import Sequence
from typing import ClassVar

from app.domain.rules.phrase_finder import PhraseFinder


class BrajDetector:
    MARKERS_NEEDED: ClassVar[int] = 2
    MARKERS_NEEDED_IN_A_BRAJ_DISTRICT: ClassVar[int] = 1
    SHORTEST_INSIDE_A_WORD: ClassVar[int] = 3  # letters, counting vowel signs
    DEVANAGARI_FIRST: ClassVar[int] = 0x0900
    DEVANAGARI_LAST: ClassVar[int] = 0x097F

    @staticmethod
    def speaks_braj(
        text: str,
        district: str | None,
        markers: Sequence[str],
        districts: Sequence[str],
    ) -> bool:
        in_braj_district = bool(district) and PhraseFinder.contains_any(district or "", districts)
        needed = (
            BrajDetector.MARKERS_NEEDED_IN_A_BRAJ_DISTRICT
            if in_braj_district
            else BrajDetector.MARKERS_NEEDED
        )
        words = [BrajDetector._undoubled(word) for word in PhraseFinder.words(text)]
        found = sum(1 for marker in markers if BrajDetector._found(words, marker))
        return found >= needed

    @staticmethod
    def _undoubled(word: str) -> str:
        """ "मेरोमेरो" → "मेरो": a word the recogniser wrote twice."""
        half = len(word) // 2
        if len(word) % 2 == 0 and half > 1 and word[:half] == word[half:]:
            return word[:half]
        return word

    @staticmethod
    def _found(words: Sequence[str], marker: str) -> bool:
        if PhraseFinder.positions(words, marker):
            return True
        normalised = PhraseFinder.normalise(marker)
        inside_a_word = (
            " " not in normalised
            and len(normalised) >= BrajDetector.SHORTEST_INSIDE_A_WORD
            and BrajDetector._is_devanagari(normalised)
        )
        return inside_a_word and any(BrajDetector._ends_here(word, normalised) for word in words)

    @staticmethod
    def _ends_here(word: str, marker: str) -> bool:
        """`marker` inside `word`, not continued by a vowel sign: "करत" isn't in "करते"
        (standard Hindi), but "मेरो" is in a run-together "ललितमेरो"."""
        start = word.find(marker)
        while start != -1:
            after = start + len(marker)
            if after == len(word) or not BrajDetector._is_vowel_sign(word[after]):
                return True
            start = word.find(marker, start + 1)
        return False

    @staticmethod
    def _is_vowel_sign(letter: str) -> bool:
        return unicodedata.category(letter) in {"Mn", "Mc"}

    @staticmethod
    def _is_devanagari(text: str) -> bool:
        return all(
            BrajDetector.DEVANAGARI_FIRST <= ord(letter) <= BrajDetector.DEVANAGARI_LAST
            for letter in text
        )
