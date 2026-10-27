"""ChildReplyMatcher: what a reply to a child must never say (s07 d8 and the d1 child rule,
s10b §4.16). Pure; the phrase lists are reviewed constants passed in.

- Secrecy, exclusivity and attachment ("kisi ko mat batana", "only I understand you"): d8.
- A question asking the child for personal details (school, address, phone, family members'
  names): d1. Telling the child to talk to their parents is fine, and the known nickname is.
"""

from collections.abc import Sequence

from app.domain.rules.phrase_finder import PhraseFinder


class ChildReplyMatcher:
    @staticmethod
    def manipulates(reply_text: str, manipulation_phrases: Sequence[str]) -> bool:
        return PhraseFinder.contains_any(reply_text, manipulation_phrases)

    @staticmethod
    def asks_personal_details(
        reply_text: str, question_words: Sequence[str], personal_topics: Sequence[str]
    ) -> bool:
        """A sentence that asks something (a question mark or a question word) about a
        personal topic."""
        for sentence in ChildReplyMatcher.sentences(reply_text):
            asks = "?" in sentence or PhraseFinder.contains_any(sentence, question_words)
            if asks and PhraseFinder.contains_any(sentence, personal_topics):
                return True
        return False

    @staticmethod
    def sentences(text: str) -> list[str]:
        """Split after . ? ! । and line ends, keeping the marks."""
        sentences: list[str] = []
        current: list[str] = []
        for character in text:
            current.append(character)
            if character in ".?!।\n":
                sentences.append("".join(current))
                current = []
        if current:
            sentences.append("".join(current))
        return sentences
