"""LocalVoice: the line every prompt's language rule ends with (owner, 2026-10-28).

Village examples for everyone, and, in Hindi and Hinglish, light Braj for a Braj speaker (one
who writes in Braj, or lives in a Braj district). English is unchanged apart from the village
examples.
"""

from app.constants.braj_words import BRAJ_DISTRICTS, BRAJ_MARKERS, BRAJ_RULE, VILLAGE_RULE
from app.domain.enums import Language
from app.domain.models.turn import TurnContext
from app.domain.rules.braj_detector import BrajDetector


class LocalVoice:
    @staticmethod
    def rule(
        register: Language, district: str | None, text: str, *, heard_braj: bool = False
    ) -> str:
        """`heard_braj`: intent reading heard Braj in the words, beyond the marker words."""
        braj = BRAJ_RULE.get(register)
        if braj is not None and (
            heard_braj or BrajDetector.speaks_braj(text, district, BRAJ_MARKERS, BRAJ_DISTRICTS)
        ):
            return f"{VILLAGE_RULE} {braj}"
        return VILLAGE_RULE

    @staticmethod
    def for_turn(register: Language, ctx: TurnContext, user_text: str) -> str:
        return LocalVoice.rule(register, ctx.profile.district, user_text, heard_braj=ctx.heard_braj)

    @staticmethod
    def language_rule(base: str, register: Language, ctx: TurnContext, user_text: str) -> str:
        """`base` (the layer's own language rule) followed by the local-voice line."""
        return f"{base} {LocalVoice.for_turn(register, ctx, user_text)}"
