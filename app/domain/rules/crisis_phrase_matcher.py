"""CrisisPhraseMatcher: the crisis rules that need no provider (s07 §4.5 rule 1, §4.6). Pure.

Recall first: a false positive sends a helpline to someone who didn't need it, which is
acceptable; a miss isn't. Text and phrases are normalised the same way (NFC, casefold, nukta and
nasal marks dropped, anything but letters and digits to spaces), then matched as whole-word
sequences, so "Jeene ka MANN nahi!!" matches "jeene ka mann nahi".
"""

import unicodedata
from collections.abc import Sequence
from typing import ClassVar

from app.domain.enums import SafetyCategory
from app.domain.models.safety import CrisisLexicon


class CrisisPhraseMatcher:
    _DROPPED_MARKS: ClassVar[frozenset[str]] = frozenset(
        {
            "़",  # nukta: ख़ुदकुशी and खुदकुशी are the same word to a reader
            "ँ",  # chandrabindu
            "ं",  # anusvara: नहीं and नही are both written
        }
    )

    @staticmethod
    def normalise(text: str) -> str:
        decomposed = unicodedata.normalize("NFD", text.casefold())
        kept: list[str] = []
        for character in decomposed:
            if character in CrisisPhraseMatcher._DROPPED_MARKS:
                continue
            category = unicodedata.category(character)
            kept.append(character if category[0] in {"L", "M", "N"} else " ")
        return " ".join(unicodedata.normalize("NFC", "".join(kept)).split())

    @staticmethod
    def find(text: str, lexicon: CrisisLexicon) -> frozenset[SafetyCategory]:
        words = CrisisPhraseMatcher.normalise(text).split()
        found: set[SafetyCategory] = set()
        if any(
            CrisisPhraseMatcher._positions(words, phrase) for phrase in lexicon.self_harm_phrases
        ):
            found.add(SafetyCategory.SELF_HARM)
        if CrisisPhraseMatcher._is_abuse_disclosure(words, lexicon):
            found.add(SafetyCategory.ABUSE_DISCLOSURE)
        return frozenset(found)

    @staticmethod
    def _is_abuse_disclosure(words: Sequence[str], lexicon: CrisisLexicon) -> bool:
        people_at: list[int] = []
        for person in lexicon.abuse_people:
            people_at.extend(CrisisPhraseMatcher._positions(words, person))
        harms_at: list[int] = []
        for harm in lexicon.abuse_harms:
            harms_at.extend(CrisisPhraseMatcher._positions(words, harm))
        return any(
            abs(person_at - harm_at) <= lexicon.abuse_window_tokens
            for person_at in people_at
            for harm_at in harms_at
        )

    @staticmethod
    def _positions(words: Sequence[str], phrase: str) -> list[int]:
        """Where the phrase starts in `words`, as a whole-word sequence."""
        phrase_words = CrisisPhraseMatcher.normalise(phrase).split()
        if not phrase_words:
            return []
        span = len(phrase_words)
        return [
            start
            for start in range(len(words) - span + 1)
            if list(words[start : start + span]) == phrase_words
        ]
