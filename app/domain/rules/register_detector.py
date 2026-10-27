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
    DEVANAGARI_AT_LEAST: ClassVar[float] = 0.6  # Hindi text: Roman exam names are fine
    DEVANAGARI_AT_MOST: ClassVar[float] = 0.05  # Roman text: a stray Devanagari word is fine

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

    @staticmethod
    def script_problems(written: str, spoken: str, register: Language) -> list[str]:
        """Fixed-vocabulary problems for a repair turn: is the text, and the spoken text, in the
        register's script? Hindi text is Devanagari; Hinglish and English text is Roman; spoken
        text is Devanagari for Hindi and Hinglish (the Hindi voice), Roman for English."""
        problems: list[str] = []
        written_share = RegisterDetector.devanagari_share(written) or 0.0
        spoken_share = RegisterDetector.devanagari_share(spoken) or 0.0
        wants_devanagari_text = register is Language.HINDI
        wants_devanagari_speech = register in {Language.HINDI, Language.HINGLISH}
        if wants_devanagari_text and written_share < RegisterDetector.DEVANAGARI_AT_LEAST:
            problems.append("text: expected Devanagari script")
        if not wants_devanagari_text and written_share > RegisterDetector.DEVANAGARI_AT_MOST:
            problems.append("text: expected Roman script")
        if wants_devanagari_speech and spoken_share < RegisterDetector.DEVANAGARI_AT_LEAST:
            problems.append("spoken_text: expected Devanagari script")
        if not wants_devanagari_speech and spoken_share > RegisterDetector.DEVANAGARI_AT_MOST:
            problems.append("spoken_text: expected English in Roman script")
        return problems
