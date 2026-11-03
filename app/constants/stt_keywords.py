"""Speech-to-text hints: words Muse Voice Transcribe might mishear (s06 §4.5). Reviewed copy.

Keywords bias the recogniser toward these spellings; they don't guarantee them. Version 1 holds
the parent journey's own words; Phase 2 adds the exam, scheme and institution names from the
corpus. Reviewed by the owner (2026-11-03); changes go to docs/reviews/owner-review-pending.md.
"""

from typing import Final

STT_KEYWORDS_VERSION: Final = "1"
STT_KEYWORDS: Final[tuple[str, ...]] = (
    "Marg",
    "khoj",
    "aaj ki khoj",
    "doosri khoj",
    "anganwadi",
    "ASHA didi",
)
