"""SafetyDecisionMapper: categories → ALLOW / BLOCK / CRISIS and the reply variant (s07 §4.4)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.constants.fixed_replies import FIXED_TEXTS, FixedTextKey
from app.domain.enums import (
    FixedReplyKind,
    FixedReplyVariant,
    Language,
    SafetyCategory,
    SafetyDecision,
)
from app.safety.safety_decision_mapper import SafetyDecisionMapper

pytestmark = pytest.mark.unit

C = SafetyCategory
CATEGORY_SETS = st.lists(st.sampled_from(list(SafetyCategory)), max_size=6)


def test_both_tables_cover_every_category() -> None:
    assert set(SafetyDecisionMapper.INPUT) == set(SafetyCategory)
    assert set(SafetyDecisionMapper.OUTPUT) == set(SafetyCategory)


def test_anything_flagged_in_our_own_reply_is_blocked() -> None:
    assert set(SafetyDecisionMapper.OUTPUT.values()) == {SafetyDecision.BLOCK}


def test_nothing_flagged_is_allowed_with_no_variant() -> None:
    assert SafetyDecisionMapper.decide([], SafetyDecisionMapper.INPUT) == (
        SafetyDecision.ALLOW,
        None,
    )


@pytest.mark.parametrize(
    ("categories", "expected"),
    [
        ([C.SELF_HARM], (SafetyDecision.CRISIS, FixedReplyVariant.SELF_HARM)),
        ([C.ABUSE_DISCLOSURE], (SafetyDecision.CRISIS, FixedReplyVariant.ABUSE)),
        ([C.HATE, C.SELF_HARM], (SafetyDecision.CRISIS, FixedReplyVariant.SELF_HARM)),
        ([C.ABUSE_DISCLOSURE, C.SELF_HARM], (SafetyDecision.CRISIS, FixedReplyVariant.SELF_HARM)),
        ([C.VIOLENT_CRIMES], (SafetyDecision.BLOCK, FixedReplyVariant.HARMFUL)),
        (
            [C.INDISCRIMINATE_WEAPONS],
            (SafetyDecision.BLOCK, FixedReplyVariant.DANGEROUS_MAKING),
        ),
        (
            [C.INDISCRIMINATE_WEAPONS, C.VIOLENT_CRIMES],
            (SafetyDecision.BLOCK, FixedReplyVariant.HARMFUL),
        ),
        # golden case student-mentor-011: firecracker powder at home is S9 and S2 (4/4)
        (
            [C.INDISCRIMINATE_WEAPONS, C.NON_VIOLENT_CRIMES],
            (SafetyDecision.BLOCK, FixedReplyVariant.DANGEROUS_MAKING),
        ),
        (
            [C.INDISCRIMINATE_WEAPONS, C.NON_VIOLENT_CRIMES, C.VIOLENT_CRIMES],
            (SafetyDecision.BLOCK, FixedReplyVariant.HARMFUL),
        ),
        ([C.NON_VIOLENT_CRIMES], (SafetyDecision.BLOCK, FixedReplyVariant.HARMFUL)),
        (
            [C.INDISCRIMINATE_WEAPONS, C.MEDICAL],
            (SafetyDecision.BLOCK, FixedReplyVariant.DANGEROUS_MAKING),
        ),
        ([C.PRIVACY, C.MEDICAL], (SafetyDecision.BLOCK, FixedReplyVariant.PRIVACY)),
        ([C.MEDICAL], (SafetyDecision.BLOCK, FixedReplyVariant.MEDICAL)),
        ([C.ROMANTIC], (SafetyDecision.BLOCK, FixedReplyVariant.GENERAL)),
        ([C.SPECIALIZED_ADVICE, C.ELECTIONS], (SafetyDecision.ALLOW, None)),
    ],
)
def test_user_message_precedence_and_variant(
    categories: list[SafetyCategory], expected: tuple[SafetyDecision, FixedReplyVariant | None]
) -> None:
    assert SafetyDecisionMapper.decide(categories, SafetyDecisionMapper.INPUT) == expected


def test_a_flagged_reply_never_becomes_crisis() -> None:
    decision, _ = SafetyDecisionMapper.decide([C.SELF_HARM], SafetyDecisionMapper.OUTPUT)
    assert decision is SafetyDecision.BLOCK


@given(categories=CATEGORY_SETS)
def test_decision_is_the_most_severe_over_the_set(categories: list[SafetyCategory]) -> None:
    decision, variant = SafetyDecisionMapper.decide(categories, SafetyDecisionMapper.INPUT)
    singles = {SafetyDecisionMapper.INPUT[category] for category in categories}
    if SafetyDecision.CRISIS in singles:
        assert decision is SafetyDecision.CRISIS
    elif SafetyDecision.BLOCK in singles:
        assert decision is SafetyDecision.BLOCK
    else:
        assert decision is SafetyDecision.ALLOW
    assert (variant is None) == (decision is SafetyDecision.ALLOW)


@given(categories=CATEGORY_SETS)
def test_order_of_categories_never_changes_the_outcome(categories: list[SafetyCategory]) -> None:
    forward = SafetyDecisionMapper.decide(categories, SafetyDecisionMapper.INPUT)
    backward = SafetyDecisionMapper.decide(list(reversed(categories)), SafetyDecisionMapper.INPUT)
    assert forward == backward


@pytest.mark.parametrize("language", list(Language))
def test_the_weapons_refusal_redirects_to_a_safe_way_to_learn(language: Language) -> None:
    """Owner, 2026-10-28: "can I make a rocket from firecracker powder?" never gets a method,
    but is told never to make one and where to learn safely."""
    key = FixedTextKey(FixedReplyKind.REFUSE, FixedReplyVariant.DANGEROUS_MAKING, language)
    text = FIXED_TEXTS[key].text
    teacher = {
        Language.HINGLISH: "science teacher",
        Language.HINDI: "विज्ञान शिक्षक",
        Language.ENGLISH: "science teacher",
    }
    never = {
        Language.HINGLISH: "Kabhi khud mat",
        Language.HINDI: "कभी ख़ुद मत",
        Language.ENGLISH: "Never make one",
    }
    assert teacher[language] in text
    assert never[language] in text
