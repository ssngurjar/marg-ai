"""RegisterChooser: which language to answer this message in (owner, 2026-10-28).

The family's language (from onboarding) holds unless the message clearly shows another. A few
words say little: "ok", "bye", "haan ji" and "Main Munni hoon" read as English, and flipped a
Hinglish parent's reply to English. So:
- writing in Devanagari means Hindi, however short (the script is a strong signal);
- otherwise a different language counts only from MIN_WORDS words up;
- with no known language yet, the message decides (as before).
"""

from typing import ClassVar

from app.domain.enums import Language
from app.domain.rules.phrase_finder import PhraseFinder
from app.domain.rules.register_detector import RegisterDetector


class RegisterChooser:
    MIN_WORDS: ClassVar[int] = 4

    @staticmethod
    def choose(text: str, usual: Language | None) -> Language | None:
        """The register for this reply; None only when neither the message nor the profile
        says (the caller falls back to Hinglish)."""
        detected = RegisterDetector.detect(text)
        if detected is None or usual is None or detected is usual:
            return detected or usual
        if detected is Language.HINDI:
            return detected  # wrote in Devanagari
        if len(PhraseFinder.words(text)) >= RegisterChooser.MIN_WORDS:
            return detected
        return usual
