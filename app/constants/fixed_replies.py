"""Fixed replies: reviewed copy keyed by (kind, variant, language) (contracts §6).

Never generated, never translated. Each kind is added, in every language, by the step that first
sends it: S4 adds TRY_AGAIN_LATER (the poisoned-turn reply); S5, S6, S7, S8 and S10b add theirs.
`FixedReplyService` reads these; a startup check makes sure every kind exists in every language.
"""

from dataclasses import dataclass
from typing import Final

from app.domain.enums import FixedReplyKind, FixedReplyVariant, Language

FALLBACK_LANGUAGE: Final = Language.HINGLISH  # used when the user's language isn't known yet


@dataclass(frozen=True, slots=True)
class FixedText:
    text: str
    spoken_text: str  # what TTS reads: no URLs, markdown or emoji
    version: str


@dataclass(frozen=True, slots=True)
class FixedTextKey:
    kind: FixedReplyKind
    variant: FixedReplyVariant
    language: Language


_TRY_AGAIN_LATER_HINGLISH = (
    "Maaf kijiye, abhi jawab dene mein dikkat aa rahi hai. Thodi der baad phir se message kijiye."
)
_TRY_AGAIN_LATER_HINDI = "माफ़ कीजिए, अभी जवाब देने में दिक्कत आ रही है। थोड़ी देर बाद फिर से संदेश भेजिए।"
_TRY_AGAIN_LATER_ENGLISH = (
    "Sorry, I can't reply right now. Please send your message again in a little while."
)

FIXED_TEXTS: Final[dict[FixedTextKey, FixedText]] = {
    FixedTextKey(FixedReplyKind.TRY_AGAIN_LATER, FixedReplyVariant.DEFAULT, Language.HINGLISH): (
        FixedText(_TRY_AGAIN_LATER_HINGLISH, _TRY_AGAIN_LATER_HINGLISH, version="1")
    ),
    FixedTextKey(FixedReplyKind.TRY_AGAIN_LATER, FixedReplyVariant.DEFAULT, Language.HINDI): (
        FixedText(_TRY_AGAIN_LATER_HINDI, _TRY_AGAIN_LATER_HINDI, version="1")
    ),
    FixedTextKey(FixedReplyKind.TRY_AGAIN_LATER, FixedReplyVariant.DEFAULT, Language.ENGLISH): (
        FixedText(_TRY_AGAIN_LATER_ENGLISH, _TRY_AGAIN_LATER_ENGLISH, version="1")
    ),
}
