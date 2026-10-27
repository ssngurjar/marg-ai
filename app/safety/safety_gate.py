"""SafetyGate: every message in and every reply out is checked, and its sealed `SafeReply`
(s07 §4.2).

No outbox row exists without a `SafeReply`, and only this module can create one: the seal is a
module-private token that `SafeReply.__post_init__` checks. Fixed texts are sealed without a
classifier call (`clear_fixed`); generated replies only after Llama Guard allows them
(`check_output`). Any classifier failure raises SafetyUnavailable, and the pipeline fails closed.

The user's message gets three checks (s07 §4.5, pulled into S5 after spike B):
1. the crisis phrase rules, first and offline: a match is CRISIS without waiting for anyone;
2. Llama Guard and the Muse Spark policy check, concurrently. Llama Guard's S1, S2 and S4 on a
   user's message count only when the policy check confirms the message asks for harm (spike B:
   it flagged ordinary parent questions with them). Its S11 always counts: recall first. When
   the policy check is switched off, Llama Guard's codes stand as they are;
3. the most severe decision over everything flagged.
Our reply is checked by Llama Guard alone (owner, 2026-10-27).
"""

import asyncio
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import ClassVar, Final, Literal

from app.core.errors import ProviderError, SafetyUnavailable
from app.domain.enums import (
    FixedReplyKind,
    FixedReplyVariant,
    Language,
    SafetyCategory,
    SafetyDecision,
)
from app.domain.models.reply import Citation, LocalisedReply, ReplyButton
from app.domain.models.safety import SafetyVerdict
from app.domain.models.usage import StepUsage
from app.providers.ports import SafetyClassifier, SafetyRequest
from app.safety.domain_policy import DomainPolicy, PolicyFindings
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
    usage: StepUsage | None  # None when the phrase rules decided without a provider call


@dataclass(frozen=True, slots=True)
class OutputCheck:
    """The verdict on our reply: `safe_reply` is set only when it was allowed."""

    verdict: SafetyVerdict
    safe_reply: SafeReply | None
    usage: StepUsage


class SafetyGate:
    NEEDS_CONFIRMATION: ClassVar[frozenset[SafetyCategory]] = frozenset(
        {
            SafetyCategory.VIOLENT_CRIMES,
            SafetyCategory.NON_VIOLENT_CRIMES,
            SafetyCategory.CHILD_EXPLOITATION,
        }
    )
    """Llama Guard codes that count on a user's message only if the policy check confirms harm."""

    def __init__(self, classifier: SafetyClassifier, policy: DomainPolicy) -> None:
        self._classifier = classifier
        self._policy = policy

    async def check_input(self, user_text: str) -> InputCheck:
        """Classify the user's message. Raises SafetyUnavailable if a provider check fails,
        unless the phrase rules already found a crisis."""
        rule_categories = self._policy.scan_input_rules(user_text)
        if rule_categories:
            return self._input_check(rule_categories, source="domain_policy", usages=[])
        guard_task = asyncio.create_task(
            self._classify(SafetyRequest(speaker="user", text=user_text, prior_user_text=None))
        )
        policy_task = asyncio.create_task(self._policy_findings(user_text))
        try:
            (guard_verdict, guard_usage), findings = await asyncio.gather(guard_task, policy_task)
        except SafetyUnavailable:
            guard_task.cancel()
            policy_task.cancel()
            await asyncio.gather(guard_task, policy_task, return_exceptions=True)
            raise
        guard_categories = set(guard_verdict.categories)
        usages = [guard_usage]
        policy_categories: frozenset[SafetyCategory] = frozenset()
        if findings is not None:
            usages.append(findings.usage)
            policy_categories = findings.categories
            if not findings.asks_for_harm:
                guard_categories -= self.NEEDS_CONFIRMATION
        source: Literal["llama_guard", "domain_policy"] = (
            "domain_policy" if policy_categories and not guard_categories else "llama_guard"
        )
        return self._input_check(guard_categories | policy_categories, source, usages)

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

    async def _policy_findings(self, user_text: str) -> PolicyFindings | None:
        try:
            return await self._policy.check_input_model(user_text)
        except ProviderError as exc:
            raise SafetyUnavailable(f"policy model user check failed: {exc}") from exc

    @staticmethod
    def _input_check(
        categories: Collection[SafetyCategory],
        source: Literal["llama_guard", "domain_policy"],
        usages: list[StepUsage],
    ) -> InputCheck:
        flagged = sorted(categories)
        decision, variant = SafetyDecisionMapper.decide(flagged, SafetyDecisionMapper.INPUT)
        verdict = SafetyVerdict(decision=decision, categories=flagged, source=source)
        return InputCheck(verdict=verdict, variant=variant, usage=StepUsage.total(usages))

    async def _classify(self, request: SafetyRequest) -> tuple[SafetyVerdict, StepUsage]:
        try:
            return await self._classifier.classify(request)
        except ProviderError as exc:
            raise SafetyUnavailable(f"llama_guard {request.speaker} check failed: {exc}") from exc
