"""IndicScriptNormaliser: a Hindi voice note heard in another Indian script, put back into
Devanagari (owner, 2026-10-28).

Speech-to-text sometimes returns spoken Hindi or Braj in Gujarati script ("મેરો ચોરા સ્કૂલ"
for "मेरो छोरा स्कूल"). Marg's users speak Hindi, Hinglish or English, so that is always a
recognition slip, and every later step (safety, the Braj check, the layers) expects Devanagari.
The Brahmic scripts below sit in Unicode blocks laid out in parallel to Devanagari's, so each
letter maps across by a fixed offset: deterministic, no model, and anything outside those
blocks (Devanagari, Roman, digits, emoji) is left exactly as it is.
"""

from typing import ClassVar, Final

DEVANAGARI_START: Final = 0x0900
BLOCK_SIZE: Final = 0x80


class IndicScriptNormaliser:
    BLOCKS: ClassVar[dict[str, int]] = {
        "bengali": 0x0980,
        "gurmukhi": 0x0A00,
        "gujarati": 0x0A80,
        "oriya": 0x0B00,
    }
    """Scripts whose letters sit at the same place in their block as Devanagari's."""

    @staticmethod
    def to_devanagari(text: str) -> str:
        characters: list[str] = []
        for character in text:
            code = ord(character)
            for start in IndicScriptNormaliser.BLOCKS.values():
                if start <= code < start + BLOCK_SIZE:
                    code = DEVANAGARI_START + (code - start)
                    break
            characters.append(chr(code))
        return "".join(characters)
