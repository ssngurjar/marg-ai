"""Fixed replies: reviewed constants keyed by (kind, variant, language) (contracts §6).

Never generated, never translated, and sealed by `SafetyGate.clear_fixed` without a classifier
call. Each kind is added, in every language, by the step that first sends it: S4 adds
TRY_AGAIN_LATER (the poisoned-turn reply); S5, S6, S7, S8 and S10b add theirs.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.core.errors import ConfigError
from app.domain.enums import FixedReplyKind, Language
from app.domain.replies import LocalisedReply

FALLBACK_LANGUAGE: Final = Language.HINGLISH  # used when the user's language isn't known yet


class FixedReplyVariant(StrEnum):
    DEFAULT = "default"
    HARMFUL = "harmful"
    PRIVACY = "privacy"
    MEDICAL = "medical"
    GENERAL = "general"
    GENERIC = "generic"
    SELF_HARM = "self_harm"
    ABUSE = "abuse"


@dataclass(frozen=True, slots=True)
class FixedText:
    text: str
    spoken_text: str  # what TTS reads: no URLs, markdown or emoji
    version: str


@dataclass(frozen=True, slots=True)
class _FixedKey:
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

FIXED_TEXTS: Final[dict[_FixedKey, FixedText]] = {
    _FixedKey(FixedReplyKind.TRY_AGAIN_LATER, FixedReplyVariant.DEFAULT, Language.HINGLISH): (
        FixedText(_TRY_AGAIN_LATER_HINGLISH, _TRY_AGAIN_LATER_HINGLISH, version="1")
    ),
    _FixedKey(FixedReplyKind.TRY_AGAIN_LATER, FixedReplyVariant.DEFAULT, Language.HINDI): (
        FixedText(_TRY_AGAIN_LATER_HINDI, _TRY_AGAIN_LATER_HINDI, version="1")
    ),
    _FixedKey(FixedReplyKind.TRY_AGAIN_LATER, FixedReplyVariant.DEFAULT, Language.ENGLISH): (
        FixedText(_TRY_AGAIN_LATER_ENGLISH, _TRY_AGAIN_LATER_ENGLISH, version="1")
    ),
}


def localise_fixed(
    kind: FixedReplyKind, variant: FixedReplyVariant, language: Language | None
) -> LocalisedReply:
    """The fixed reply for `kind` in the user's language (Hinglish when it isn't known yet)."""
    register = language or FALLBACK_LANGUAGE
    fixed = FIXED_TEXTS.get(_FixedKey(kind, variant, register))
    if fixed is None:
        raise ConfigError(f"no fixed text for {kind.value}/{variant.value}/{register.value}")
    return LocalisedReply(
        text=fixed.text,
        spoken_text=fixed.spoken_text,
        reply_register=register,
        citations=[],
        buttons=[],
    )


def check_fixed_texts() -> None:
    """Startup check: every registered (kind, variant) has a text in every language."""
    registered = {(key.kind, key.variant) for key in FIXED_TEXTS}
    missing: list[str] = []
    for kind, variant in sorted(registered):
        for language in Language:
            if _FixedKey(kind, variant, language) not in FIXED_TEXTS:
                missing.append(f"{kind.value}/{variant.value}/{language.value}")
    if missing:
        raise ConfigError(f"fixed texts missing: {', '.join(missing)}")
