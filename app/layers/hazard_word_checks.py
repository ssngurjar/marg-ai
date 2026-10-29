"""HazardWordChecks: the d7 hazard rule as a repair problem, before safety_out sees the reply.

safety_out blocks a journey reply that names a hazard the activity didn't declare (s10b §4.10,
d7). A reflection or a parent answer that does ("frogs live near the pond") used to go
straight to the fixed "couldn't answer" reply; now the model first gets one repair turn naming
the words to leave out (owner's judge walkthrough, 2026-10-29). safety_out stays as strict.
"""

from collections.abc import Collection

from app.constants.child_hazards import CHILD_HAZARD_WORDS
from app.domain.rules.child_hazard_matcher import ChildHazardMatcher


class HazardWordChecks:
    @staticmethod
    def problems(text: str, declared: Collection[str]) -> list[str]:
        words = ChildHazardMatcher.undeclared_words(text, CHILD_HAZARD_WORDS, declared)
        if not words:
            return []
        named = ", ".join(f'"{word}"' for word in words)
        return [
            f"text: names {named}; a reply about a young child must not mention these: say it"
            " without them"
        ]
