"""DomainPolicy: what Llama Guard misses about our users (s07 §4.5), on the user's message.

Two detectors next to Llama Guard:
- the crisis phrase rules (CrisisPhraseMatcher over CRISIS_LEXICON), which need no provider;
- the Muse Spark policy check (`minor_policy` prompt), behind SAFETY_POLICY_MODEL_ENABLED.

And the backup for Llama Guard on our own reply (`reply_policy` prompt), used only when Llama
Guard fails, so a reply is never sent unchecked and never held just because one host is down.

Spike B (docs/spikes/safety-guard.md) showed Llama Guard 4 misses distress and abuse
disclosures and flags ordinary parent questions as S1/S2/S4, so the policy check also reports
whether the message asks for harm, which the gate uses to confirm those two codes.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.constants.crisis_lexicon import CRISIS_LEXICON
from app.domain.enums import SafetyCategory
from app.domain.models.safety import CrisisLexicon
from app.domain.models.usage import StepUsage
from app.domain.rules.crisis_phrase_matcher import CrisisPhraseMatcher
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel

type HarmKind = Literal["none", "violence", "weapons", "crime", "hate", "sexual", "child_sexual"]


class MinorPolicyCheck(BaseModel):
    """The policy model's structured answer (strict schema: every field required)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    self_harm_signal: bool
    abuse_disclosure: bool
    medical_advice_request: bool
    romantic_content: bool
    harm_kind: HarmKind
    reason: str = Field(max_length=120)  # helps the model decide; never logged or stored


MINOR_POLICY: Final = PromptSpec(prompt_id="minor_policy", output_type=MinorPolicyCheck)


class ReplyPolicyCheck(BaseModel):
    """The backup check on our own reply, used when Llama Guard is down (owner, 2026-10-27)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    harm_kind: HarmKind
    encourages_self_harm: bool
    medical_instructions: bool
    endangers_child: bool
    reason: str = Field(max_length=120)  # helps the model decide; never logged or stored


REPLY_POLICY: Final = PromptSpec(prompt_id="reply_policy", output_type=ReplyPolicyCheck)


@dataclass(frozen=True, slots=True)
class PolicyModel:
    llm: LanguageModel
    registry: PromptRegistry


@dataclass(frozen=True, slots=True)
class PolicyFindings:
    categories: frozenset[SafetyCategory]
    asks_for_harm: bool  # confirms Llama Guard's S1 / S2 / S4 on a user's message
    usage: StepUsage


class DomainPolicy:
    HARM_CATEGORIES: Final[Mapping[HarmKind, SafetyCategory]] = MappingProxyType(
        {
            "violence": SafetyCategory.VIOLENT_CRIMES,
            "weapons": SafetyCategory.INDISCRIMINATE_WEAPONS,
            "crime": SafetyCategory.NON_VIOLENT_CRIMES,
            "hate": SafetyCategory.HATE,
            "sexual": SafetyCategory.SEXUAL_CONTENT,
            "child_sexual": SafetyCategory.CHILD_EXPLOITATION,
        }
    )

    def __init__(
        self, *, model: PolicyModel | None, lexicon: CrisisLexicon = CRISIS_LEXICON
    ) -> None:
        """`model=None` when SAFETY_POLICY_MODEL_ENABLED is off: only the phrase rules run."""
        self._model = model
        self._lexicon = lexicon

    @property
    def model_enabled(self) -> bool:
        return self._model is not None

    def scan_input_rules(self, user_text: str) -> frozenset[SafetyCategory]:
        """The crisis phrase rules: SELF_HARM and ABUSE_DISCLOSURE. Pure and synchronous."""
        return CrisisPhraseMatcher.find(user_text, self._lexicon)

    async def check_input_model(self, user_text: str) -> PolicyFindings | None:
        """The Muse Spark policy check; None when it's switched off. Raises ProviderError."""
        if self._model is None:
            return None
        rendered = self._model.registry.render(
            MINOR_POLICY, system_vars={}, user_vars={"message": user_text}
        )
        result = await self._model.llm.generate(rendered.request)
        return self.findings_from(result.output, result.usage)

    async def check_output_model(self, reply_text: str, user_text: str) -> PolicyFindings | None:
        """The Muse Spark backup check on our reply; None when the policy model is switched off.
        Raises ProviderError."""
        if self._model is None:
            return None
        rendered = self._model.registry.render(
            REPLY_POLICY,
            system_vars={},
            user_vars={"parent_message": user_text, "reply": reply_text},
        )
        result = await self._model.llm.generate(rendered.request)
        return self.reply_findings_from(result.output, result.usage)

    @staticmethod
    def reply_findings_from(check: ReplyPolicyCheck, usage: StepUsage) -> PolicyFindings:
        categories: set[SafetyCategory] = set()
        if check.harm_kind != "none":
            categories.add(DomainPolicy.HARM_CATEGORIES[check.harm_kind])
        if check.encourages_self_harm:
            categories.add(SafetyCategory.SELF_HARM)
        if check.medical_instructions:
            categories.add(SafetyCategory.MEDICAL)
        if check.endangers_child:
            categories.add(SafetyCategory.CHILD_PHYSICAL_HAZARD)
        return PolicyFindings(
            categories=frozenset(categories),
            asks_for_harm=check.harm_kind != "none",
            usage=usage,
        )

    @staticmethod
    def findings_from(check: MinorPolicyCheck, usage: StepUsage) -> PolicyFindings:
        categories: set[SafetyCategory] = set()
        if check.self_harm_signal:
            categories.add(SafetyCategory.SELF_HARM)
        if check.abuse_disclosure:
            categories.add(SafetyCategory.ABUSE_DISCLOSURE)
        if check.medical_advice_request:
            categories.add(SafetyCategory.MEDICAL)
        if check.romantic_content:
            categories.add(SafetyCategory.ROMANTIC)
        if check.harm_kind != "none":
            categories.add(DomainPolicy.HARM_CATEGORIES[check.harm_kind])
        return PolicyFindings(
            categories=frozenset(categories),
            asks_for_harm=check.harm_kind != "none",
            usage=usage,
        )
