"""Words a personalised khoj or reflection may not use (s10b §4.7, §4.8): careers and exams for a
young child, and labels for a child. Matched as whole words after PhraseFinder.normalise.

Ambiguous words are left out on purpose ("slow like a cow" and "how fast" are activity language,
not labels). v1, written 2026-10-27: pending the owner's review.
"""

from typing import Final

CAREER_WORDS: Final = (
    "career", "engineer", "doctor", "ias", "ips", "neet", "jee", "upsc", "exam", "exams",
    "ban jaayega", "ban jayega", "ban jaayegi", "ban jayegi", "banega", "banegi", "करियर",
    "इंजीनियर", "डॉक्टर", "परीक्षा", "बनेगा", "बनेगी",
)  # fmt: skip
LABEL_WORDS: Final = (
    "genius", "dull", "stupid", "naughty", "lazy", "weak", "kamzor", "budhu", "buddhu",
    "nalayak", "shaitan", "aalsi", "कमज़ोर", "कमजोर", "बुद्धू", "नालायक", "शैतान", "आलसी",
)  # fmt: skip
# The curiosity moment may say who explores something (C12) but never push the child toward it.
EXPOSURE_PUSH_WORDS: Final = (
    "you should become", "you can become", "you will become", "tum bhi ban", "aap bhi ban",
    "tum ban sakte", "tum ban sakti", "ban sakte ho", "ban sakti ho", "banna chahiye", "bano",
    "तुम भी बन", "बन सकते हो", "बन सकती हो", "बनना चाहिए",
)  # fmt: skip
