"""The onboarding and student-routing banks stay valid test sets (their scripts run them)."""

from collections import Counter

import pytest

from app.domain.enums import ConversationState
from scripts.onboarding_bank import OnboardingBank
from scripts.student_route_bank import StudentRouteBank

pytestmark = pytest.mark.unit

ONBOARDING = OnboardingBank.load()
STUDENT = StudentRouteBank.load()


def test_every_onboarding_question_has_at_least_five_answers() -> None:
    counts = Counter(case.state for case in ONBOARDING.cases)
    asked = [
        ConversationState.AWAITING_CONSENT,
        ConversationState.AWAITING_ROLE,
        ConversationState.AWAITING_GUARDIAN,
        ConversationState.AWAITING_CHILD,
        ConversationState.AWAITING_PROFILE,
    ]
    assert {state: counts[state] for state in asked if counts[state] < 5} == {}


def test_profile_answers_name_the_role_they_belong_to() -> None:
    needs_role = {ConversationState.AWAITING_PROFILE, ConversationState.AWAITING_GUARDIAN}
    assert [
        case.text for case in ONBOARDING.cases if case.state in needs_role and case.role is None
    ] == []


def test_no_answer_is_in_the_onboarding_bank_twice_for_the_same_question() -> None:
    seen = Counter((case.state, case.role, case.text.strip().lower()) for case in ONBOARDING.cases)
    assert [key for key, count in seen.items() if count > 1] == []


def test_the_student_bank_has_both_routes_and_no_repeats() -> None:
    routes = Counter(case.route for case in STUDENT.cases)
    texts = Counter(case.text.strip().lower() for case in STUDENT.cases)
    assert routes["roadmap"] >= 10
    assert routes["mentor"] >= 10
    assert [text for text, count in texts.items() if count > 1] == []
