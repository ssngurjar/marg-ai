"""FillerDetector: a transcript of only "umm" or "hmm" is nothing said (s06 §8, CLAUDE.md §4). Pure.

Only sounds are filler. Short words that answer something ("haan", "nahi", "accha", "ok") are
never filler: they can be a real answer to a question.
"""

from typing import ClassVar

from app.domain.rules.phrase_finder import PhraseFinder


class FillerDetector:
    FILLER_SOUNDS: ClassVar[frozenset[str]] = frozenset(
        {
            "um", "umm", "ummm", "uh", "uhh", "uhm", "hm", "hmm", "hmmm", "mm", "mmm", "ah",
            "aah", "er", "erm", "eh", "उम", "उम्म", "हम", "हम्म", "अं", "आं", "आ", "अ",
        }
    )  # fmt: skip

    @staticmethod
    def is_only_filler(transcript: str) -> bool:
        """True when nothing but filler sounds is left (and so for an empty transcript)."""
        sounds = {PhraseFinder.normalise(sound) for sound in FillerDetector.FILLER_SOUNDS}
        words = PhraseFinder.words(transcript)
        return all(word in sounds for word in words)
