"""DomainPolicy builders for tests: phrase rules only, or with scripted Muse Spark checks."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.safety.domain_policy import DomainPolicy, HarmKind, PolicyModel
from tests.fakes.language_model import (
    FakeLanguageModel,
    PromptRoutedLanguageModel,
    ScriptedOutput,
)
from tests.support.prompts import shipped_registry


def policy_answer(
    *,
    self_harm: bool = False,
    abuse: bool = False,
    medical: bool = False,
    romantic: bool = False,
    harm: HarmKind = "none",
) -> dict[str, object]:
    """A `minor_policy` answer on the user's message."""
    return {
        "self_harm_signal": self_harm,
        "abuse_disclosure": abuse,
        "medical_advice_request": medical,
        "romantic_content": romantic,
        "harm_kind": harm,
        "reason": "scripted",
    }


def reply_answer(
    *,
    harm: HarmKind = "none",
    self_harm: bool = False,
    medical: bool = False,
    endangers_child: bool = False,
) -> dict[str, object]:
    """A `reply_policy` answer on our reply (the backup when Llama Guard is down)."""
    return {
        "harm_kind": harm,
        "encourages_self_harm": self_harm,
        "medical_instructions": medical,
        "endangers_child": endangers_child,
        "reason": "scripted",
    }


def image_answer(
    *,
    harm: HarmKind = "none",
    self_harm: bool = False,
    endangers_child: bool = False,
    private: bool = False,
) -> dict[str, object]:
    """An `image_policy` answer on a card or a photo (the backup when Llama Guard is down)."""
    return {
        "harm_kind": harm,
        "shows_self_harm": self_harm,
        "endangers_child": endangers_child,
        "shows_private_details": private,
        "reason": "scripted",
    }


CLEAR = policy_answer()
REPLY_CLEAR = reply_answer()
IMAGE_CLEAR = image_answer()


def rules_only_policy() -> DomainPolicy:
    """SAFETY_POLICY_MODEL_ENABLED off: only the crisis phrase rules run, and no backup."""
    return DomainPolicy(model=None)


@dataclass(frozen=True, slots=True)
class ScriptedPolicy:
    policy: DomainPolicy
    input_llm: FakeLanguageModel  # the minor_policy check on the user's message
    reply_llm: FakeLanguageModel  # the reply_policy backup on our reply
    image_llm: FakeLanguageModel  # the image_policy backup on a card or a photo


def scripted_policies(
    outputs: Sequence[ScriptedOutput] = (CLEAR,),
    reply_outputs: Sequence[ScriptedOutput] = (REPLY_CLEAR,),
    *,
    image_outputs: Sequence[ScriptedOutput] = (IMAGE_CLEAR,),
    delay_s: float = 0.0,
) -> ScriptedPolicy:
    input_llm = FakeLanguageModel(outputs, delay_s=delay_s)
    reply_llm = FakeLanguageModel(reply_outputs, delay_s=delay_s)
    image_llm = FakeLanguageModel(image_outputs, delay_s=delay_s)
    llm = PromptRoutedLanguageModel(
        {"minor_policy": input_llm, "reply_policy": reply_llm, "image_policy": image_llm}
    )
    policy = DomainPolicy(model=PolicyModel(llm, shipped_registry()))
    return ScriptedPolicy(policy, input_llm, reply_llm, image_llm)


def scripted_policy(
    outputs: Sequence[ScriptedOutput] = (CLEAR,),
    reply_outputs: Sequence[ScriptedOutput] = (REPLY_CLEAR,),
    *,
    delay_s: float = 0.0,
) -> tuple[DomainPolicy, FakeLanguageModel]:
    """The policy and the fake behind its check on the user's message."""
    scripted = scripted_policies(outputs, reply_outputs, delay_s=delay_s)
    return scripted.policy, scripted.input_llm
