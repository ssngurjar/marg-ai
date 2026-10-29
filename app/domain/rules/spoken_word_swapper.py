"""SpokenWordSwapper: the words the voice says badly, replaced in text about to be spoken."""

import re
from collections.abc import Mapping
from typing import ClassVar


class SpokenWordSwapper:
    # A Devanagari letter or vowel sign on either side means the word is part of a longer one;
    # the danda (।, ॥) and the digits (U+0964-U+0970) are not letters.
    _DEVANAGARI: ClassVar[str] = "\\u0900-\\u0963\\u0971-\\u097f"

    @staticmethod
    def swap(text: str, swaps: Mapping[str, str]) -> str:
        """Each whole word in `swaps` replaced by its spoken form; idempotent when no spoken
        form contains a word that is itself swapped."""
        swapped = text
        for written, spoken in swaps.items():
            pattern = re.compile(
                rf"(?<![{SpokenWordSwapper._DEVANAGARI}]){re.escape(written)}"
                rf"(?![{SpokenWordSwapper._DEVANAGARI}])"
            )
            swapped = pattern.sub(spoken, swapped)
        return swapped
