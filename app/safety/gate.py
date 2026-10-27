"""The safety gate and its sealed output, `SafeReply` (s07 §4.2).

No outbox row exists without a `SafeReply`, and only this module can create one: the seal is a
module-private token that `SafeReply.__post_init__` checks. S4 builds the fixed-text path
(`clear_fixed`); S5 adds `check_input` and `check_output` with the classifier.
"""

from dataclasses import dataclass, field
from typing import Final

from app.domain.enums import FixedReplyKind, Language, SafetyDecision
from app.domain.replies import Citation, LocalisedReply, ReplyButton
from app.domain.safety import SafetyVerdict

_SEAL: Final = object()


@dataclass(frozen=True, slots=True)
class SafeReply:
    text: str
    spoken_text: str
    reply_register: Language
    citations: tuple[Citation, ...]
    buttons: tuple[ReplyButton, ...]
    verdict: SafetyVerdict
    fixed_kind: FixedReplyKind | None
    _seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _SEAL:
            raise TypeError("SafeReply can only be created by SafetyGate")


class SafetyGate:
    def clear_fixed(self, reply: LocalisedReply, kind: FixedReplyKind) -> SafeReply:
        """Seal a fixed reply. Fixed texts are reviewed constants, so no classifier call is made."""
        return SafeReply(
            text=reply.text,
            spoken_text=reply.spoken_text,
            reply_register=reply.reply_register,
            citations=tuple(reply.citations),
            buttons=tuple(reply.buttons),
            verdict=SafetyVerdict(decision=SafetyDecision.ALLOW, categories=[], source="fixed"),
            fixed_kind=kind,
            _seal=_SEAL,
        )
