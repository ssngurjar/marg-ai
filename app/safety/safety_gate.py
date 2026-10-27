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
Our reply is checked by Llama Guard; a flag gets a second opinion from the Muse Spark reply
check, and the reply is sent only if that finds nothing (owner, 2026-10-27).

Llama Guard down (owner, 2026-10-27, after DeepInfra overloads): each Llama Guard call has its
own short limit (TIMEOUT_GUARD_S). If it fails, the user's message is decided by the phrase rules
and the policy check, which ran anyway, and our reply by the Muse Spark reply check. Text is never
sent unchecked: SafetyUnavailable (and the HOLDING reply) only when the backup fails too.
"""

import asyncio
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import timedelta
from typing import ClassVar, Final, Literal

from app.constants.child_hazards import CHILD_HAZARD_WORDS
from app.constants.child_safety_words import (
    CHILD_MANIPULATION_PHRASES,
    CHILD_PERSONAL_TOPICS,
    QUESTION_WORDS,
)
from app.core.errors import ProviderError, SafetyUnavailable
from app.core.logging import get_logger
from app.domain.enums import (
    FixedReplyKind,
    FixedReplyVariant,
    Language,
    SafetyCategory,
    SafetyDecision,
    Speaker,
)
from app.domain.models.reply import Citation, LocalisedReply, ReplyButton
from app.domain.models.safety import SafetyVerdict
from app.domain.models.usage import StepUsage
from app.domain.rules.child_hazard_matcher import ChildHazardMatcher
from app.domain.rules.child_reply_matcher import ChildReplyMatcher
from app.providers.ports import SafetyClassifier, SafetyRequest
from app.safety.domain_policy import DomainPolicy, PolicyFindings
from app.safety.safety_decision_mapper import SafetyDecisionMapper

_SEAL: Final = object()
DEFAULT_GUARD_TIMEOUT: Final = timedelta(seconds=1.5)  # TIMEOUT_GUARD_S; wiring passes the setting

logger = get_logger(__name__)


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
    guard_down: bool = False  # Llama Guard failed and the backup decided


@dataclass(frozen=True, slots=True)
class OutputCheck:
    """The verdict on our reply: `safe_reply` is set only when it was allowed."""

    verdict: SafetyVerdict
    safe_reply: SafeReply | None
    usage: StepUsage | None  # None when the d7 rule blocked before any provider call
    guard_down: bool = False  # Llama Guard failed and the Muse Spark reply check decided
    overruled: tuple[SafetyCategory, ...] = ()  # Llama Guard codes the second opinion cleared


@dataclass(frozen=True, slots=True)
class _OutputVerdict:
    verdict: SafetyVerdict
    usage: StepUsage | None
    guard_down: bool
    overruled: tuple[SafetyCategory, ...]

    def result(self, *, safe_reply: SafeReply | None) -> OutputCheck:
        return OutputCheck(
            verdict=self.verdict,
            safe_reply=safe_reply,
            usage=self.usage,
            guard_down=self.guard_down,
            overruled=self.overruled,
        )


@dataclass(frozen=True, slots=True)
class _GuardAnswer:
    verdict: SafetyVerdict
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

    def __init__(
        self,
        classifier: SafetyClassifier,
        policy: DomainPolicy,
        *,
        guard_timeout: timedelta = DEFAULT_GUARD_TIMEOUT,
    ) -> None:
        self._classifier = classifier
        self._policy = policy
        self._guard_timeout = guard_timeout

    async def check_input(self, user_text: str) -> InputCheck:
        """Classify the user's message. Raises SafetyUnavailable when the policy check fails,
        or when Llama Guard and the policy check both do, unless the phrase rules found a crisis."""
        rule_categories = self._policy.scan_input_rules(user_text)
        if rule_categories:
            return self._input_check(rule_categories, "domain_policy", [], guard_down=False)
        request = SafetyRequest(speaker="user", text=user_text, prior_user_text=None)
        guard_task = asyncio.create_task(self._guard(request))
        policy_task = asyncio.create_task(self._policy_findings(user_text))
        try:
            guard, findings = await asyncio.gather(guard_task, policy_task)
        except SafetyUnavailable:
            guard_task.cancel()
            policy_task.cancel()
            await asyncio.gather(guard_task, policy_task, return_exceptions=True)
            raise
        if guard is None and findings is None:
            raise SafetyUnavailable("llama_guard user check failed and no policy check is on")
        usages: list[StepUsage] = []
        guard_categories: set[SafetyCategory] = set()
        if guard is not None:
            guard_categories = set(guard.verdict.categories)
            usages.append(guard.usage)
        policy_categories: frozenset[SafetyCategory] = frozenset()
        if findings is not None:
            usages.append(findings.usage)
            policy_categories = findings.categories
            if not findings.asks_for_harm:
                guard_categories -= self.NEEDS_CONFIRMATION
        source: Literal["llama_guard", "domain_policy"] = (
            "llama_guard"
            if guard_categories or (guard and not policy_categories)
            else "domain_policy"
        )
        return self._input_check(
            guard_categories | policy_categories, source, usages, guard_down=guard is None
        )

    async def check_output(
        self,
        reply: LocalisedReply,
        user_text: str,
        *,
        hazard_rule: frozenset[str] | None = None,
        speaker: Speaker = Speaker.GUIDE,
    ) -> OutputCheck:
        """Classify our reply in the context of the user's message; seal it only if allowed.

        A Llama Guard flag gets a second opinion from the Muse Spark reply check: the reply is
        sent only if that finds nothing (owner, 2026-10-27: a harmless answer on teaching
        colours was flagged S2 every time). If the second opinion fails, the flag stands.
        `hazard_rule` (journey replies, s10b §4.10): the hazards the offered activity declares.
        Any other physical hazard for a young child in the reply blocks it before any provider
        call (d7). Raises SafetyUnavailable when Llama Guard and the backup check both fail.
        The spoken text becomes the voice note, so when it differs from the text, both are
        classified together: nothing is spoken that wasn't checked (CLAUDE.md §11, S6).
        """
        classified_text = SafetyGate.text_to_classify(reply)
        child_rule = SafetyGate._child_rule(classified_text, speaker)
        if child_rule is not None:
            verdict = SafetyVerdict(
                decision=SafetyDecision.BLOCK, categories=[child_rule], source="domain_policy"
            )
            return OutputCheck(verdict=verdict, safe_reply=None, usage=None)
        if hazard_rule is not None:
            undeclared = ChildHazardMatcher.undeclared(
                f"{reply.text} {reply.spoken_text}", CHILD_HAZARD_WORDS, hazard_rule
            )
            if undeclared:
                verdict = SafetyVerdict(
                    decision=SafetyDecision.BLOCK,
                    categories=[SafetyCategory.CHILD_PHYSICAL_HAZARD],
                    source="domain_policy",
                )
                return OutputCheck(verdict=verdict, safe_reply=None, usage=None)
        request = SafetyRequest(
            speaker="assistant", text=classified_text, prior_user_text=user_text
        )
        guard = await self._guard(request)
        overruled: tuple[SafetyCategory, ...] = ()
        source: Literal["llama_guard", "domain_policy"] = "llama_guard"
        if guard is None:
            findings = await self._reply_findings(classified_text, user_text)
            categories = sorted(findings.categories)
            usage = findings.usage
            source = "domain_policy"
        elif guard.verdict.categories and self._policy.model_enabled:
            categories, usage, overruled = await self._second_opinion(
                guard, classified_text, user_text
            )
            if overruled:
                source = "domain_policy"
        else:
            categories = list(guard.verdict.categories)
            usage = guard.usage
        decision, _ = SafetyDecisionMapper.decide(categories, SafetyDecisionMapper.OUTPUT)
        verdict = SafetyVerdict(decision=decision, categories=categories, source=source)
        checked = _OutputVerdict(verdict, usage, guard_down=guard is None, overruled=overruled)
        if decision is not SafetyDecision.ALLOW:
            return checked.result(safe_reply=None)
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
        return checked.result(safe_reply=safe)

    @staticmethod
    def _child_rule(classified_text: str, speaker: Speaker) -> SafetyCategory | None:
        """Deterministic rules for children (C13): d8 on every reply (no secrecy or attachment,
        s07 §4.5), and on a reply to a child, no question asking for personal details (d1)."""
        if ChildReplyMatcher.manipulates(classified_text, CHILD_MANIPULATION_PHRASES):
            return SafetyCategory.CHILD_MANIPULATION
        if speaker is Speaker.LEARNER and ChildReplyMatcher.asks_personal_details(
            classified_text, QUESTION_WORDS, CHILD_PERSONAL_TOPICS
        ):
            return SafetyCategory.MINOR_PII
        return None

    @staticmethod
    def text_to_classify(reply: LocalisedReply) -> str:
        """The text, and the spoken text after it when the two differ."""
        if reply.spoken_text.strip() == reply.text.strip():
            return reply.text
        return f"{reply.text}\n\n{reply.spoken_text}"

    async def _second_opinion(
        self, guard: _GuardAnswer, classified_text: str, user_text: str
    ) -> tuple[list[SafetyCategory], StepUsage, tuple[SafetyCategory, ...]]:
        """Categories to decide on, the usage of both calls, and any Llama Guard codes cleared."""
        flagged = list(guard.verdict.categories)
        try:
            findings = await self._reply_findings(classified_text, user_text)
        except SafetyUnavailable as exc:
            logger.warning("second_opinion_failed", error=type(exc.__cause__).__name__)
            return flagged, guard.usage, ()
        usage = StepUsage.total([guard.usage, findings.usage]) or guard.usage
        if findings.categories:
            return sorted(set(flagged) | findings.categories), usage, ()
        return [], usage, tuple(flagged)

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

    async def _reply_findings(self, reply_text: str, user_text: str) -> PolicyFindings:
        try:
            findings = await self._policy.check_output_model(reply_text, user_text)
        except ProviderError as exc:
            raise SafetyUnavailable(
                f"llama_guard and the backup reply check both failed: {exc}"
            ) from exc
        if findings is None:
            raise SafetyUnavailable("llama_guard assistant check failed and no backup is on")
        return findings

    async def _guard(self, request: SafetyRequest) -> _GuardAnswer | None:
        """Llama Guard within its own limit; None when it fails, so the backup decides."""
        try:
            async with asyncio.timeout(self._guard_timeout.total_seconds()):
                verdict, usage = await self._classifier.classify(request)
        except (ProviderError, TimeoutError) as exc:
            logger.warning("llama_guard_down", speaker=request.speaker, error=type(exc).__name__)
            return None
        return _GuardAnswer(verdict, usage)

    @staticmethod
    def _input_check(
        categories: Collection[SafetyCategory],
        source: Literal["llama_guard", "domain_policy"],
        usages: list[StepUsage],
        *,
        guard_down: bool,
    ) -> InputCheck:
        flagged = sorted(categories)
        decision, variant = SafetyDecisionMapper.decide(flagged, SafetyDecisionMapper.INPUT)
        verdict = SafetyVerdict(decision=decision, categories=flagged, source=source)
        return InputCheck(
            verdict=verdict,
            variant=variant,
            usage=StepUsage.total(usages),
            guard_down=guard_down,
        )
