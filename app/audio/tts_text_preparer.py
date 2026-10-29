"""TtsTextPreparer: the deterministic gate between `spoken_text` and the synthesizer (s06 §4.6).

The reply's spoken text is written in Devanagari for Hindi and Hinglish (C11), English for
English. Here it's normalised, cleaned of what a voice can't say (emoji, symbols, markdown,
links), checked for script, and split into sentences. Letters the voice can't read (anything but
Devanagari for the Hindi voice, anything but Latin for the English one), a text too long to
speak, or one word too long for a TTS sentence raise TtsTextInvalid: the reply goes out as text
only, never as garbled or cut audio. The full text message is unaffected.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import ClassVar, Literal

from app.core.errors import TtsTextInvalid
from app.domain.enums import Language

type Voice = Literal["hin", "eng"]


@dataclass(frozen=True, slots=True)
class TtsText:
    voice: Voice
    sentences: tuple[str, ...]


class TtsTextPreparer:
    MAX_SENTENCE_CHARS: ClassVar[int] = 250  # TTS_MAX_SENTENCE_CHARS
    MAX_SPOKEN_CHARS: ClassVar[int] = 1200  # TTS_MAX_SPOKEN_CHARS, about 75 s of speech
    _URL: ClassVar[re.Pattern[str]] = re.compile(r"(https?://|www\.)\S+")
    _SENTENCE_END: ClassVar[re.Pattern[str]] = re.compile(r"(?<=[।?!.])\s+|\n+")
    _DEVANAGARI: ClassVar[re.Pattern[str]] = re.compile(r"[\u0900-\u097F\uA8E0-\uA8FF]")
    _AFTER_COMMA: ClassVar[re.Pattern[str]] = re.compile(r"(?<=,)\s+")
    # "छोटा-छोटा": MMS pauses at the hyphen and the doubled word sounds read out, not spoken
    # (owner's listening test, 2026-10-29); a space between Hindi words reads naturally.
    _HINDI_HYPHEN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?<=[\u0900-\u097F])-(?=[\u0900-\u097F])"
    )
    _SPEAKABLE_PUNCTUATION: ClassVar[frozenset[str]] = frozenset("।?!.,;:'\"-()")

    @staticmethod
    def prepare(spoken_text: str, register: Language) -> TtsText:
        voice: Voice = "eng" if register is Language.ENGLISH else "hin"
        cleaned = TtsTextPreparer.clean(spoken_text)
        if not cleaned:
            raise TtsTextInvalid("nothing speakable in spoken_text")
        foreign = TtsTextPreparer._foreign_letters(cleaned, voice)
        if foreign:
            raise TtsTextInvalid(f"{foreign} letters in {voice} spoken_text")
        if len(cleaned) > TtsTextPreparer.MAX_SPOKEN_CHARS:
            raise TtsTextInvalid("spoken_text too long")
        sentences: list[str] = []
        for sentence in TtsTextPreparer._SENTENCE_END.split(cleaned):
            sentences.extend(TtsTextPreparer._fit(sentence.strip()))
        return TtsText(voice=voice, sentences=tuple(part for part in sentences if part))

    @staticmethod
    def clean(text: str) -> str:
        """NFC, links removed, a hyphen between Hindi words made a space, only letters, marks,
        digits, spaces and sentence punctuation kept, whitespace collapsed. Idempotent."""
        normalised = unicodedata.normalize("NFC", TtsTextPreparer._URL.sub(" ", text))
        normalised = TtsTextPreparer._HINDI_HYPHEN.sub(" ", normalised)
        kept: list[str] = []
        for character in normalised:
            category = unicodedata.category(character)
            if (
                category[0] in {"L", "M", "N"}
                or character in TtsTextPreparer._SPEAKABLE_PUNCTUATION
            ):
                kept.append(character)
            elif character == "\n":
                kept.append("\n")
            else:
                kept.append(" ")
        lines = [" ".join(line.split()) for line in "".join(kept).split("\n")]
        return "\n".join(line for line in lines if line)

    @staticmethod
    def _foreign_letters(cleaned: str, voice: Voice) -> str | None:
        """The script the voice can't read, if any: the Hindi voice reads only Devanagari
        letters, the English voice only Latin ones. Digits and punctuation are fine for both."""
        for character in cleaned:
            if not unicodedata.category(character).startswith(("L", "M")):
                continue
            is_devanagari = TtsTextPreparer._DEVANAGARI.match(character) is not None
            if voice == "hin" and not is_devanagari:
                return "non-devanagari"
            if voice == "eng" and not ("A" <= character <= "Z" or "a" <= character <= "z"):
                return "non-latin"
        return None

    @staticmethod
    def _fit(sentence: str) -> list[str]:
        """Split a sentence over the limit between clauses (after commas) where it can, and
        between words inside a clause that is itself too long; never mid-word."""
        limit = TtsTextPreparer.MAX_SENTENCE_CHARS
        if len(sentence) <= limit:
            return [sentence]
        units: list[str] = []
        for clause in TtsTextPreparer._AFTER_COMMA.split(sentence):
            units.extend([clause] if len(clause) <= limit else clause.split())
        return TtsTextPreparer._pack(units)

    @staticmethod
    def _pack(units: list[str]) -> list[str]:
        """Join units with spaces into pieces of at most the limit, in order."""
        limit = TtsTextPreparer.MAX_SENTENCE_CHARS
        pieces: list[str] = []
        current = ""
        for unit in units:
            if len(unit) > limit:
                raise TtsTextInvalid("a word longer than one tts sentence")
            candidate = f"{current} {unit}" if current else unit
            if len(candidate) <= limit:
                current = candidate
                continue
            pieces.append(current)
            current = unit
        if current:
            pieces.append(current)
        return pieces
