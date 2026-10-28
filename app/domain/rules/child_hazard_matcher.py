"""ChildHazardMatcher: which physical hazards a text mentions (d7, s10b §4.10). Pure."""

from collections.abc import Collection, Mapping, Sequence

from app.domain.rules.phrase_finder import PhraseFinder


class ChildHazardMatcher:
    @staticmethod
    def find(text: str, hazard_words: Mapping[str, Sequence[str]]) -> frozenset[str]:
        """The hazard kinds whose words appear in `text`, as whole words."""
        words = PhraseFinder.words(text)
        return frozenset(
            hazard
            for hazard, phrases in hazard_words.items()
            if any(PhraseFinder.positions(words, phrase) for phrase in phrases)
        )

    @staticmethod
    def undeclared(
        text: str, hazard_words: Mapping[str, Sequence[str]], declared: Collection[str]
    ) -> frozenset[str]:
        """Hazards mentioned that the activity didn't declare (and so have no safety note)."""
        return ChildHazardMatcher.find(text, hazard_words) - frozenset(declared)

    @staticmethod
    def asked_about(
        question: str, hazard_words: Mapping[str, Sequence[str]], never: Collection[str]
    ) -> frozenset[str]:
        """Hazards the child's own question names: an answer may talk about them (owner,
        2026-10-28: "saanp ke kaan kahan hote hain?" needs the word snake), but an activity
        may never involve them. `never`: kinds no answer discusses even then (medicine)."""
        return ChildHazardMatcher.find(question, hazard_words) - frozenset(never)
