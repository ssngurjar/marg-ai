"""ChildQuestionDetector: is the parent passing on the child's own question? (s10b §4.15). Pure.

The deterministic half of the curiosity-moment trigger; the `curiosity_moment` prompt confirms
it. A message counts when it asks something (a question mark or a question word) AND says the
question is the child's: a word for asking ("poochh rahi hai", "asked", "पूछ रहा") or the
child's nickname. "Beta khana nahi khata, kya karein?" is the parent's own question and stays
with the parent answer (flow D).
"""

from collections.abc import Iterable
from typing import ClassVar

from app.domain.rules.phrase_finder import PhraseFinder


class ChildQuestionDetector:
    QUESTION_WORDS: ClassVar[frozenset[str]] = frozenset(
        {
            "kyun", "kyon", "kyu", "kaise", "kaisa", "kya", "kahan", "kahaan", "kab", "kaun",
            "kitna", "kitne", "why", "how", "what", "where", "when", "who", "क्यों", "कैसे",
            "क्या", "कहाँ", "कहां", "कब", "कौन", "कितना", "कितने",
        }
    )  # fmt: skip
    ASKING_WORD_STARTS: ClassVar[tuple[str, ...]] = (
        "poochh", "puchh", "pooch", "puch", "पूछ", "पुछ", "asked", "asks", "asking",
    )  # fmt: skip
    ASKING_PHRASES: ClassVar[tuple[str, ...]] = (
        "jaanna chahti", "jaanna chahta", "janna chahti", "janna chahta", "wants to know",
        "जानना चाहती", "जानना चाहता",
    )  # fmt: skip

    @staticmethod
    def relays_child_question(text: str, nicknames: Iterable[str | None]) -> bool:
        words = PhraseFinder.words(text)
        return ChildQuestionDetector.asks(text) and ChildQuestionDetector._is_the_childs(
            text, words, nicknames
        )

    @staticmethod
    def asks(text: str) -> bool:
        """A question mark, or a question word anywhere."""
        question_words = {
            PhraseFinder.normalise(word) for word in ChildQuestionDetector.QUESTION_WORDS
        }
        return "?" in text or any(word in question_words for word in PhraseFinder.words(text))

    @staticmethod
    def _is_the_childs(text: str, words: list[str], nicknames: Iterable[str | None]) -> bool:
        asking_starts = tuple(
            PhraseFinder.normalise(start) for start in ChildQuestionDetector.ASKING_WORD_STARTS
        )
        if any(word.startswith(asking_starts) for word in words):
            return True
        if PhraseFinder.contains_any(text, ChildQuestionDetector.ASKING_PHRASES):
            return True
        named = [nickname for nickname in nicknames if nickname]
        return PhraseFinder.contains_any(text, named)
