"""SafetyGate: every message in and every reply out is checked, and its sealed `SafeReply`
(s07 §4.2).

No outbox row exists without a `SafeReply`, and only this module can create one: the seal is a
module-private token that `SafeReply.__post_init__` checks. Fixed texts are sealed without a
classifier call (`clear_fixed`); generated replies only after Llama Guard allows them
(`check_output`). Any classifier failure raises SafetyUnavailable, and the pipeline fails closed.
S7 adds the domain policy (lexicon, policy model) on top of these checks.
"""

from dataclasses import dataclass, field
from typing import Final

from app.core.errors import ProviderError, SafetyUnavailable
from app.domain.enums import FixedReplyKind, FixedReplyVariant, Language, SafetyDecision
from app.domain.models.reply import Citation, LocalisedReply, ReplyButton
from app.domain.models.safety import SafetyVerdict
from app.domain.models.usage import StepUsage
from app.providers.ports import SafetyClassifier, SafetyRequest
from app.safety.safety_decision_mapper import SafetyDecisionMapper

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


@dataclass(frozen=True, slots=True)
class InputCheck:
    """The verdict on a user's message. `variant` picks the REFUSE or CRISIS text when not ALLOW."""

    verdict: SafetyVerdict
    variant: FixedReplyVariant | None
    usage: StepUsage


@dataclass(frozen=True, slots=True)
class OutputCheck:
    """The verdict on our reply: `safe_reply` is set only when it was allowed."""

    verdict: SafetyVerdict
    safe_reply: SafeReply | None
    usage: StepUsage


class SafetyGate:
    def __init__(self, classifier: SafetyClassifier) -> None:
        self._classifier = classifier

    async def check_input(self, user_text: str) -> InputCheck:
        """Classify the user's message. Raises SafetyUnavailable if the classifier fails."""
        raw, usage = await self._classify(
            SafetyRequest(speaker="user", text=user_text, prior_user_text=None)
        )
        decision, variant = SafetyDecisionMapper.decide(raw.categories, SafetyDecisionMapper.INPUT)
        verdict = SafetyVerdict(decision=decision, categories=raw.categories, source=raw.source)
        return InputCheck(verdict=verdict, variant=variant, usage=usage)

    async def check_output(self, reply: LocalisedReply, user_text: str) -> OutputCheck:
        """Classify our reply in the context of the user's message; seal it only if allowed."""
        request = SafetyRequest(speaker="assistant", text=reply.text, prior_user_text=user_text)
        raw, usage = await self._classify(request)
        decision, _ = SafetyDecisionMapper.decide(raw.categories, SafetyDecisionMapper.OUTPUT)
        verdict = SafetyVerdict(decision=decision, categories=raw.categories, source=raw.source)
        if decision is not SafetyDecision.ALLOW:
            return OutputCheck(verdict=verdict, safe_reply=None, usage=usage)
        safe = SafeReply(
            text=reply.text,
            spoken_text=reply.spoken_text,
            reply_register=reply.reply_register,
            citations=tuple(reply.citations),
            buttons=tuple(reply.buttons),
            verdict=verdict,
            fixed_kind=None,
            _seal=_SEAL,
        )
        return OutputCheck(verdict=verdict, safe_reply=safe, usage=usage)

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

    async def _classify(self, request: SafetyRequest) -> tuple[SafetyVerdict, StepUsage]:
        try:
            return await self._classifier.classify(request)
        except ProviderError as exc:
            raise SafetyUnavailable(f"llama_guard {request.speaker} check failed: {exc}") from exc
