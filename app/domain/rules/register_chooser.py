"""RegisterChooser: which language to answer this message in (owner, 2026-10-28).

The family's language (from onboarding) holds unless the message clearly shows another. A few
words say little: "ok", "bye", "haan ji" and "Main Munni hoon" read as English, and flipped a
Hinglish parent's reply to English. So:
- writing in Devanagari means Hindi, however short (the script is a strong signal);
- otherwise a different language counts only from MIN_WORDS words up;
- a shorter message follows the conversation: the language of Marg's last reply, if there is one
  (a web tester's "Ok cool 😎" after English answers got Hinglish, 2026-11-02), else the family's;
- with no known language yet, the message decides (as before).
"""

from typing import ClassVar

from app.domain.enums import Language
from app.domain.rules.phrase_finder import PhraseFinder
from app.domain.rules.register_detector import RegisterDetector


class RegisterChooser:
    MIN_WORDS: ClassVar[int] = 4

    @staticmethod
    def choose(
        text: str, usual: Language | None, conversation: Language | None = None
    ) -> Language | None:
        """The register for this reply; None only when neither the message nor the profile
        says (the caller falls back to Hinglish). `conversation`: the language of Marg's last
        reply, which a short message follows."""
        detected = RegisterDetector.detect(text)
        if detected is None:
            return conversation or usual  # nothing to read ("👍"): stay in the conversation
        if usual is None or detected is usual:
            return detected
        if detected is Language.HINDI:
            return detected  # wrote in Devanagari
        if len(PhraseFinder.words(text)) >= RegisterChooser.MIN_WORDS:
            return detected
        return conversation or usual
