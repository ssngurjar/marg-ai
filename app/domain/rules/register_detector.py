"""RegisterDetector: which language and script a message is in (s09's detect_register). Pure.

Devanagari text is HINDI. Roman text is HINGLISH when it carries common Hindi words (romanised),
otherwise ENGLISH. A message with no letters (emoji, digits) has no register: None, and the
caller falls back (Hinglish until onboarding records the parent's language).
"""

import re
import unicodedata
from typing import ClassVar

from app.domain.enums import Language


class RegisterDetector:
    DEVANAGARI_SHARE_FOR_HINDI: ClassVar[float] = 0.5
    """Hindi when at least this share of the letters are Devanagari (exam names stay Roman)."""
    HINGLISH_MARKERS_NEEDED: ClassVar[int] = 1

    _DEVANAGARI_LETTER: ClassVar[re.Pattern[str]] = re.compile("[ऀ-ॿ]")
    _ROMAN_LETTER: ClassVar[re.Pattern[str]] = re.compile("[A-Za-z]")
    _WORD: ClassVar[re.Pattern[str]] = re.compile(r"[a-z]+")
    _HINGLISH_MARKERS: ClassVar[frozenset[str]] = frozenset(
        {
            "hai", "hain", "kya", "kaise", "kyon", "kyun", "kyunki", "nahi", "nahin", "mera",
            "meri", "mere", "mujhe", "hum", "humara", "hamara", "aap", "aapka", "aapke", "tum",
            "bachcha", "bachche", "bachchi", "beta", "beti", "kar", "karna", "karein", "karo",
            "raha", "rahi", "rahe", "tha", "thi", "batao", "bataiye", "chahiye", "sakta",
            "sakti", "sakte", "abhi", "kuch", "bahut", "accha", "acha", "lekin", "aur", "ko",
            "se", "mein", "ki", "ka", "ke", "ne", "toh", "bhi", "din", "roz", "khel", "padhai",
        }
    )  # fmt: skip

    @staticmethod
    def detect(text: str) -> Language | None:
        normalised = unicodedata.normalize("NFC", text)
        devanagari = len(RegisterDetector._DEVANAGARI_LETTER.findall(normalised))
        roman = len(RegisterDetector._ROMAN_LETTER.findall(normalised))
        if devanagari + roman == 0:
            return None
        if devanagari / (devanagari + roman) >= RegisterDetector.DEVANAGARI_SHARE_FOR_HINDI:
            return Language.HINDI
        words = set(RegisterDetector._WORD.findall(normalised.casefold()))
        markers = len(words & RegisterDetector._HINGLISH_MARKERS)
        if markers >= RegisterDetector.HINGLISH_MARKERS_NEEDED:
            return Language.HINGLISH
        return Language.ENGLISH

    @staticmethod
    def devanagari_share(text: str) -> float | None:
        """Devanagari letters over Devanagari + Roman letters; None when there are neither."""
        devanagari = len(RegisterDetector._DEVANAGARI_LETTER.findall(text))
        roman = len(RegisterDetector._ROMAN_LETTER.findall(text))
        if devanagari + roman == 0:
            return None
        return devanagari / (devanagari + roman)
