"""DomainPolicy builders for tests: phrase rules only, or with a scripted policy model."""

from collections.abc import Sequence

from app.safety.domain_policy import DomainPolicy, HarmKind, PolicyModel
from tests.fakes.language_model import FakeLanguageModel, ScriptedOutput
from tests.support.prompts import shipped_registry


def policy_answer(
    *,
    self_harm: bool = False,
    abuse: bool = False,
    medical: bool = False,
    romantic: bool = False,
    harm: HarmKind = "none",
) -> dict[str, object]:
    return {
        "self_harm_signal": self_harm,
        "abuse_disclosure": abuse,
        "medical_advice_request": medical,
        "romantic_content": romantic,
        "harm_kind": harm,
        "reason": "scripted",
    }


CLEAR = policy_answer()


def rules_only_policy() -> DomainPolicy:
    """SAFETY_POLICY_MODEL_ENABLED off: only the crisis phrase rules run."""
    return DomainPolicy(model=None)


def scripted_policy(
    outputs: Sequence[ScriptedOutput] = (CLEAR,), *, delay_s: float = 0.0
) -> tuple[DomainPolicy, FakeLanguageModel]:
    llm = FakeLanguageModel(outputs, delay_s=delay_s)
    return DomainPolicy(model=PolicyModel(llm, shipped_registry())), llm
