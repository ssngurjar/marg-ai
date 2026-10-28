"""SafetyDecisionMapper: flagged categories → ALLOW / BLOCK / CRISIS, and which reply (s07 §4.4).

Two total tables, one for the user's message and one for our reply. Precedence over a set of
categories: CRISIS > BLOCK > ALLOW. The fixed-reply variant comes from the highest-priority
category: SELF_HARM > ABUSE > HARMFUL > DANGEROUS_MAKING > PRIVACY > MEDICAL > GENERAL.
"""

from collections.abc import Collection, Mapping
from types import MappingProxyType
from typing import ClassVar

from app.domain.enums import FixedReplyVariant, SafetyCategory, SafetyDecision

_C = SafetyCategory
_ALLOW = SafetyDecision.ALLOW
_BLOCK = SafetyDecision.BLOCK
_CRISIS = SafetyDecision.CRISIS


class SafetyDecisionMapper:
    INPUT: ClassVar[Mapping[SafetyCategory, SafetyDecision]] = MappingProxyType(
        {
            _C.VIOLENT_CRIMES: _BLOCK,
            _C.NON_VIOLENT_CRIMES: _BLOCK,
            _C.SEX_CRIMES: _BLOCK,
            _C.CHILD_EXPLOITATION: _BLOCK,  # S7's abuse-disclosure check upgrades to CRISIS
            _C.DEFAMATION: _ALLOW,
            _C.SPECIALIZED_ADVICE: _ALLOW,  # "how do I become a doctor" is fine; S7 decides medical
            _C.PRIVACY: _BLOCK,
            _C.INTELLECTUAL_PROPERTY: _ALLOW,
            _C.INDISCRIMINATE_WEAPONS: _BLOCK,
            _C.HATE: _BLOCK,
            _C.SELF_HARM: _CRISIS,
            _C.SEXUAL_CONTENT: _BLOCK,
            _C.ELECTIONS: _ALLOW,
            _C.CODE_INTERPRETER_ABUSE: _BLOCK,
            _C.MINOR_PII: _ALLOW,
            _C.GUARANTEE_PROMISE: _ALLOW,
            _C.ROMANTIC: _BLOCK,
            _C.MEDICAL: _BLOCK,
            _C.ABUSE_DISCLOSURE: _CRISIS,
            _C.PROMPT_LEAK: _ALLOW,
            _C.CHILD_PHYSICAL_HAZARD: _ALLOW,
            _C.CHILD_MANIPULATION: _ALLOW,
        }
    )
    OUTPUT: ClassVar[Mapping[SafetyCategory, SafetyDecision]] = MappingProxyType(
        dict.fromkeys(SafetyCategory, _BLOCK)
    )
    """Anything flagged in our own reply is blocked (s07 §4.4, "On our reply" column)."""

    _VARIANT_BY_CATEGORY: ClassVar[Mapping[SafetyCategory, FixedReplyVariant]] = MappingProxyType(
        {
            _C.SELF_HARM: FixedReplyVariant.SELF_HARM,
            _C.ABUSE_DISCLOSURE: FixedReplyVariant.ABUSE,
            _C.VIOLENT_CRIMES: FixedReplyVariant.HARMFUL,
            _C.NON_VIOLENT_CRIMES: FixedReplyVariant.HARMFUL,
            _C.SEX_CRIMES: FixedReplyVariant.HARMFUL,
            _C.CHILD_EXPLOITATION: FixedReplyVariant.HARMFUL,
            # owner, 2026-10-28: "can I make a rocket from firecracker powder?" gets a safe redirect
            _C.INDISCRIMINATE_WEAPONS: FixedReplyVariant.DANGEROUS_MAKING,
            _C.HATE: FixedReplyVariant.HARMFUL,
            _C.SEXUAL_CONTENT: FixedReplyVariant.HARMFUL,
            _C.CODE_INTERPRETER_ABUSE: FixedReplyVariant.HARMFUL,
            _C.PRIVACY: FixedReplyVariant.PRIVACY,
            _C.MEDICAL: FixedReplyVariant.MEDICAL,
        }
    )
    _VARIANT_PRIORITY: ClassVar[tuple[FixedReplyVariant, ...]] = (
        FixedReplyVariant.SELF_HARM,
        FixedReplyVariant.ABUSE,
        FixedReplyVariant.HARMFUL,
        FixedReplyVariant.DANGEROUS_MAKING,
        FixedReplyVariant.PRIVACY,
        FixedReplyVariant.MEDICAL,
        FixedReplyVariant.GENERAL,
    )
    _SEVERITY: ClassVar[Mapping[SafetyDecision, int]] = MappingProxyType(
        {_ALLOW: 0, _BLOCK: 1, _CRISIS: 2}
    )

    @staticmethod
    def decide(
        categories: Collection[SafetyCategory], table: Mapping[SafetyCategory, SafetyDecision]
    ) -> tuple[SafetyDecision, FixedReplyVariant | None]:
        """The most severe decision over `categories`, and the reply variant when not ALLOW."""
        decision = _ALLOW
        for category in categories:
            candidate = table[category]
            if SafetyDecisionMapper._SEVERITY[candidate] > SafetyDecisionMapper._SEVERITY[decision]:
                decision = candidate
        if decision is _ALLOW:
            return decision, None
        deciding = [category for category in categories if table[category] is decision]
        variants = {
            SafetyDecisionMapper._VARIANT_BY_CATEGORY.get(category, FixedReplyVariant.GENERAL)
            for category in deciding
        }
        for variant in SafetyDecisionMapper._VARIANT_PRIORITY:
            if variant in variants:
                return decision, variant
        return decision, FixedReplyVariant.GENERAL
