"""ParentMention: whether a reply to a child already sends them to Mummy and Papa (owner,
2026-11-01), so code doesn't add "Tell Mummy and Papa too!" a second time. Pure.
"""

from typing import ClassVar

from app.domain.rules.phrase_finder import PhraseFinder


class ParentMention:
    MOTHER_WORDS: ClassVar[frozenset[str]] = frozenset(
        {"mummy", "mumma", "mammi", "maa", "mother", "mom", "मम्मी", "माँ", "मां"}
    )
    FATHER_WORDS: ClassVar[frozenset[str]] = frozenset(
        {"papa", "pappa", "father", "dad", "पापा", "पिताजी"}
    )
    BOTH_WORDS: ClassVar[frozenset[str]] = frozenset(
        {"parents", "parent", "mata-pita", "माता-पिता"}
    )

    @staticmethod
    def found(text: str) -> bool:
        """Both a mother word and a father word, or a word for both ("parents")."""
        said = set(PhraseFinder.words(text))
        if said & ParentMention.BOTH_WORDS:
            return True
        return bool(said & ParentMention.MOTHER_WORDS) and bool(said & ParentMention.FATHER_WORDS)
