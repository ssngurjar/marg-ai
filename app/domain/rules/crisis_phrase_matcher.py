"""CrisisPhraseMatcher: the crisis rules that need no provider (s07 §4.5 rule 1, §4.6). Pure.

Recall first: a false positive sends a helpline to someone who didn't need it, which is
acceptable; a miss isn't. Matching is PhraseFinder's: normalised, whole-word sequences, so
"Jeene ka MANN nahi!!" matches "jeene ka mann nahi".
"""

from collections.abc import Sequence

from app.domain.enums import SafetyCategory
from app.domain.models.safety import CrisisLexicon
from app.domain.rules.phrase_finder import PhraseFinder


class CrisisPhraseMatcher:
    @staticmethod
    def find(text: str, lexicon: CrisisLexicon) -> frozenset[SafetyCategory]:
        words = PhraseFinder.words(text)
        found: set[SafetyCategory] = set()
        if any(PhraseFinder.positions(words, phrase) for phrase in lexicon.self_harm_phrases):
            found.add(SafetyCategory.SELF_HARM)
        if CrisisPhraseMatcher._is_abuse_disclosure(words, lexicon):
            found.add(SafetyCategory.ABUSE_DISCLOSURE)
        return frozenset(found)

    @staticmethod
    def _is_abuse_disclosure(words: Sequence[str], lexicon: CrisisLexicon) -> bool:
        people_at: list[int] = []
        for person in lexicon.abuse_people:
            people_at.extend(PhraseFinder.positions(words, person))
        harms_at: list[int] = []
        for harm in lexicon.abuse_harms:
            harms_at.extend(PhraseFinder.positions(words, harm))
        return any(
            abs(person_at - harm_at) <= lexicon.abuse_window_tokens
            for person_at in people_at
            for harm_at in harms_at
        )
