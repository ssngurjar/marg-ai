"""Replies to small talk that every persona gets alike (owner, 2026-11-02: what is true for one
persona's "ok" or good night is true for all). Hinglish, Hindi and English. Pending the owner's
review."""

from typing import Final

from app.domain.enums import Language

GOOD_NIGHT: Final[dict[Language, str]] = {
    Language.HINGLISH: "Shubh ratri! Kal phir baat karte hain.",
    Language.HINDI: "शुभ रात्रि! कल फिर बात करते हैं।",
    Language.ENGLISH: "Good night! Talk again tomorrow.",
}
