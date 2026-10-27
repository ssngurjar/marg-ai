"""LlamaGuardOutputParser: Llama Guard 4's answer read strictly (s07 §4.3). Pure.

Accepted, after stripping surrounding whitespace: `safe`, or `unsafe` then a newline and
`S<n>[,S<n>]*` with n in 1..14 (spaces after commas allowed). Anything else is an invalid
response: the parser never guesses, and "probably safe" is not safe.
"""

import re
from typing import ClassVar

from app.core.errors import ProviderResponseInvalid
from app.domain.enums import SafetyCategory

PROVIDER = "llama_guard"


class LlamaGuardOutputParser:
    _UNSAFE: ClassVar[re.Pattern[str]] = re.compile(r"unsafe\n(S\d{1,2}(?:, ?S\d{1,2})*)")
    LAST_CATEGORY: ClassVar[int] = 14  # Llama Guard 4's hazard codes are S1..S14

    @staticmethod
    def parse(raw: str) -> list[SafetyCategory]:
        """The categories Llama Guard flagged; [] for `safe`. Raises ProviderResponseInvalid."""
        answer = raw.strip()
        if answer == "safe":
            return []
        match = LlamaGuardOutputParser._UNSAFE.fullmatch(answer)
        if match is None:
            raise ProviderResponseInvalid(
                f"llama guard answer isn't 'safe' or 'unsafe' + codes ({len(answer)} chars)",
                provider=PROVIDER,
            )
        categories: list[SafetyCategory] = []
        for code in re.split(r", ?", match.group(1)):
            number = int(code.removeprefix("S"))
            if not 1 <= number <= LlamaGuardOutputParser.LAST_CATEGORY:
                raise ProviderResponseInvalid(
                    f"llama guard returned unknown category S{number}", provider=PROVIDER
                )
            categories.append(SafetyCategory(f"s{number}"))
        return categories
