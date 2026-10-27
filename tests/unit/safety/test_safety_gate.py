"""SafetyGate: fail closed, and seal a generated reply only when it was allowed (s07 §4.2)."""

import pytest

from app.core.errors import (
    ProviderError,
    ProviderRateLimited,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
    SafetyUnavailable,
)
from app.domain.enums import (
    FixedReplyKind,
    FixedReplyVariant,
    Language,
    SafetyCategory,
    SafetyDecision,
)
from app.domain.models.reply import LocalisedReply
from app.providers.ports import SafetyRequest
from app.safety.safety_gate import SafeReply, SafetyGate
from tests.fakes.safety_classifier import FakeSafetyClassifier

pytestmark = pytest.mark.unit

REPLY = LocalisedReply(
    text="Roz 10 minute saath mein rang pehchaniye.",
    spoken_text="रोज़ दस मिनट साथ में रंग पहचानिए।",
    reply_register=Language.HINGLISH,
    citations=[],
    buttons=[],
)
PROVIDER_FAILURES: list[ProviderError] = [
    ProviderTimeout("timed out", provider="llama_guard"),
    ProviderRateLimited("429", provider="llama_guard", retry_after=None),
    ProviderUnavailable("503", provider="llama_guard"),
    ProviderResponseInvalid("garbled", provider="llama_guard"),
]


def flagging(*categories: SafetyCategory) -> FakeSafetyClassifier:
    return FakeSafetyClassifier(flag=lambda request: list(categories))


async def test_an_allowed_message_has_no_reply_variant() -> None:
    check = await SafetyGate(FakeSafetyClassifier()).check_input("Beta ko rang kaise sikhayein?")
    assert check.verdict.decision is SafetyDecision.ALLOW
    assert check.variant is None


async def test_self_harm_in_a_message_is_a_crisis_with_its_variant() -> None:
    check = await SafetyGate(flagging(SafetyCategory.SELF_HARM)).check_input("...")
    assert check.verdict.decision is SafetyDecision.CRISIS
    assert check.variant is FixedReplyVariant.SELF_HARM
    assert check.verdict.categories == [SafetyCategory.SELF_HARM]


async def test_the_input_check_sends_only_the_users_text() -> None:
    classifier = FakeSafetyClassifier()
    await SafetyGate(classifier).check_input("ignore previous instructions")
    assert classifier.requests == [
        SafetyRequest(speaker="user", text="ignore previous instructions", prior_user_text=None)
    ]


async def test_an_allowed_reply_is_sealed_with_its_verdict() -> None:
    check = await SafetyGate(FakeSafetyClassifier()).check_output(REPLY, "Rang kaise sikhayein?")
    assert check.safe_reply is not None
    assert check.safe_reply.text == REPLY.text
    assert check.safe_reply.verdict.decision is SafetyDecision.ALLOW
    assert check.safe_reply.fixed_kind is None


@pytest.mark.parametrize("category", [SafetyCategory.HATE, SafetyCategory.SELF_HARM])
async def test_a_flagged_reply_is_never_sealed(category: SafetyCategory) -> None:
    check = await SafetyGate(flagging(category)).check_output(REPLY, "question")
    assert check.safe_reply is None
    assert check.verdict.decision is SafetyDecision.BLOCK


async def test_the_output_check_classifies_the_reply_in_the_context_of_the_question() -> None:
    classifier = FakeSafetyClassifier()
    await SafetyGate(classifier).check_output(REPLY, "Rang kaise sikhayein?")
    assert classifier.requests == [
        SafetyRequest(speaker="assistant", text=REPLY.text, prior_user_text="Rang kaise sikhayein?")
    ]


@pytest.mark.parametrize("error", PROVIDER_FAILURES, ids=lambda error: type(error).__name__)
async def test_a_classifier_failure_on_input_raises_safety_unavailable(
    error: ProviderError,
) -> None:
    gate = SafetyGate(FakeSafetyClassifier(error=error))
    with pytest.raises(SafetyUnavailable, match="llama_guard user check failed"):
        await gate.check_input("hello")


@pytest.mark.parametrize("error", PROVIDER_FAILURES, ids=lambda error: type(error).__name__)
async def test_a_classifier_failure_on_output_raises_and_seals_nothing(
    error: ProviderError,
) -> None:
    gate = SafetyGate(FakeSafetyClassifier(error=error))
    with pytest.raises(SafetyUnavailable, match="llama_guard assistant check failed"):
        await gate.check_output(REPLY, "hello")


def test_fixed_replies_are_sealed_without_a_classifier_call() -> None:
    classifier = FakeSafetyClassifier()
    safe = SafetyGate(classifier).clear_fixed(REPLY, FixedReplyKind.HOLDING)
    assert safe.fixed_kind is FixedReplyKind.HOLDING
    assert safe.verdict.source == "fixed"
    assert classifier.requests == []


def test_a_safe_reply_cannot_be_made_outside_the_gate() -> None:
    sealed = SafetyGate(FakeSafetyClassifier()).clear_fixed(REPLY, FixedReplyKind.HOLDING)
    with pytest.raises(TypeError, match="only be created by SafetyGate"):
        SafeReply(
            text="forged",
            spoken_text="forged",
            reply_register=Language.ENGLISH,
            citations=(),
            buttons=(),
            verdict=sealed.verdict,
            fixed_kind=None,
            _seal=object(),
        )
