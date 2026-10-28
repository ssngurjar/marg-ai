"""BrajDetector: does this person speak Braj (owner, 2026-10-28)? Pure; the word and district
lists are reviewed constants passed in.

Yes when their message uses two Braj forms ("mero chhora naay padh rao"), or their district is
a Braj district. One form alone isn't enough: "chhora" is said all over north India.
"""

from collections.abc import Sequence
from typing import ClassVar

from app.domain.rules.phrase_finder import PhraseFinder


class BrajDetector:
    MARKERS_NEEDED: ClassVar[int] = 2

    @staticmethod
    def speaks_braj(
        text: str,
        district: str | None,
        markers: Sequence[str],
        districts: Sequence[str],
    ) -> bool:
        if district and PhraseFinder.contains_any(district, districts):
            return True
        words = PhraseFinder.words(text)
        found = sum(1 for marker in markers if PhraseFinder.positions(words, marker))
        return found >= BrajDetector.MARKERS_NEEDED
