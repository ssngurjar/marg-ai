"""FixedReplyService: the fixed reply for a kind, in the user's language (contracts §6).

The copy itself lives in app/constants/fixed_replies.py. Fixed replies are sealed by
`SafetyGate.clear_fixed` without a classifier call.
"""

from app.constants import fixed_replies
from app.constants.fixed_replies import FALLBACK_LANGUAGE, FixedTextKey
from app.core.errors import ConfigError
from app.domain.enums import FixedReplyKind, FixedReplyVariant, Language
from app.domain.models.reply import LocalisedReply


class FixedReplyService:
    @staticmethod
    def localise(
        kind: FixedReplyKind, variant: FixedReplyVariant, language: Language | None
    ) -> LocalisedReply:
        """The fixed reply for `kind` in the user's language (Hinglish when it isn't known yet)."""
        register = language or FALLBACK_LANGUAGE
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
