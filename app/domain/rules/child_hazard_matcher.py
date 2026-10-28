"""ChildHazardMatcher: which physical hazards a text mentions (d7, s10b §4.10). Pure."""

from collections.abc import Collection, Mapping, Sequence

from app.domain.rules.phrase_finder import PhraseFinder


class ChildHazardMatcher:
    @staticmethod
    def find(
        text: str, hazard_words: Mapping[str, Sequence[str]], safe_phrases: Sequence[str] = ()
    ) -> frozenset[str]:
        """The hazard kinds whose words appear in `text`, as whole words. Words inside one of
        `safe_phrases` ("round-tip scissors") don't count."""
        words = ChildHazardMatcher._without(PhraseFinder.words(text), safe_phrases)
        return frozenset(
            hazard
            for hazard, phrases in hazard_words.items()
            if any(PhraseFinder.positions(words, phrase) for phrase in phrases)
        )

    @staticmethod
    def undeclared(
        text: str,
        hazard_words: Mapping[str, Sequence[str]],
        declared: Collection[str],
        safe_phrases: Sequence[str] = (),
    ) -> frozenset[str]:
        """Hazards mentioned that the activity didn't declare (and so have no safety note)."""
        return ChildHazardMatcher.find(text, hazard_words, safe_phrases) - frozenset(declared)

    @staticmethod
    def spoken_only(
        spoken: str,
        written: str,
        hazard_words: Mapping[str, Sequence[str]],
        safe_phrases: Sequence[str] = (),
    ) -> frozenset[str]:
        """Hazards the voice note names that the written reply doesn't: the spoken passage
        retells the written one, so a hazard only in it slipped past the activity's check."""
        return ChildHazardMatcher.find(
            spoken, hazard_words, safe_phrases
        ) - ChildHazardMatcher.find(written, hazard_words, safe_phrases)

    @staticmethod
    def _without(words: list[str], safe_phrases: Sequence[str]) -> list[str]:
        """`words` with every safe phrase blanked out, so no hazard word inside it matches."""
        kept = list(words)
        for phrase in safe_phrases:
            span = len(PhraseFinder.words(phrase))
            for start in PhraseFinder.positions(words, phrase):
                kept[start : start + span] = [""] * span
        return kept
