"""FixedReplyService: the fixed reply for a kind, in the user's language (contracts §6).

The copy itself lives in app/constants/fixed_replies.py. Fixed replies are sealed by
`SafetyGate.clear_fixed` without a classifier call.
"""

from app.constants import fixed_replies
from app.constants.child_talk_copy import (
    CHILD_CRISIS_SPOKEN,
    CHILD_CRISIS_TEXTS,
    CHILD_REFUSE,
    CHILD_REFUSE_BY_VARIANT,
    CHILD_REFUSE_OTHER,
)
from app.constants.fixed_replies import FALLBACK_LANGUAGE, FixedTextKey
from app.core.errors import ConfigError
from app.domain.enums import FixedReplyKind, FixedReplyVariant, Language, Speaker
from app.domain.models.reply import LocalisedReply


class FixedReplyService:
    @staticmethod
    def localise(
        kind: FixedReplyKind,
        variant: FixedReplyVariant,
        language: Language | None,
        speaker: Speaker = Speaker.GUIDE,
    ) -> LocalisedReply:
        """The fixed reply for `kind` in the user's language (Hinglish when it isn't known yet).
        A child talking (C13) gets the child-worded crisis and refusal texts."""
        register = language or FALLBACK_LANGUAGE
        if speaker is Speaker.LEARNER:
            child_text = FixedReplyService._for_child(kind, variant, register)
            if child_text is not None:
                return child_text
        fixed = fixed_replies.FIXED_TEXTS.get(FixedTextKey(kind, variant, register))
        if fixed is None:
            raise ConfigError(f"no fixed text for {kind.value}/{variant.value}/{register.value}")
        return LocalisedReply(
            text=fixed.text,
            spoken_text=fixed.spoken_text,
            reply_register=register,
            citations=[],
            buttons=[],
        )

    @staticmethod
    def check_all_languages() -> None:
        """Startup check: every registered (kind, variant) has a text in every language."""
        texts = fixed_replies.FIXED_TEXTS
        registered = {(key.kind, key.variant) for key in texts}
        missing: list[str] = []
        for kind, variant in sorted(registered):
            for language in Language:
                if FixedTextKey(kind, variant, language) not in texts:
                    missing.append(f"{kind.value}/{variant.value}/{language.value}")
        if missing:
            raise ConfigError(f"fixed texts missing: {', '.join(missing)}")

    @staticmethod
    def _for_child(
        kind: FixedReplyKind, variant: FixedReplyVariant, register: Language
    ) -> LocalisedReply | None:
        voice = Language.HINDI if register is Language.HINGLISH else register
        if kind is FixedReplyKind.CRISIS:
            text = CHILD_CRISIS_TEXTS.get((variant, register))
            spoken = CHILD_CRISIS_SPOKEN.get((variant, voice))
        elif kind is FixedReplyKind.REFUSE:
            copy = (
                CHILD_REFUSE
                if variant is FixedReplyVariant.MEDICAL
                else CHILD_REFUSE_BY_VARIANT.get(variant, CHILD_REFUSE_OTHER)
            )
            text, spoken = copy[register], copy[voice]
        else:
            return None
        if text is None or spoken is None:
            raise ConfigError(f"no child text for {kind.value}/{variant.value}/{register.value}")
        return LocalisedReply(
            text=text, spoken_text=spoken, reply_register=register, citations=[], buttons=[]
        )
