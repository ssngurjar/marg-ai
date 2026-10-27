"""TurnRouter: deterministic routing, no model call (s05 §4.4, s08 §4.6)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.enums import ConversationState, Role, Route
from app.pipeline.turn_router import TurnRouter
from tests.support.turn_context import user_profile

pytestmark = pytest.mark.unit

PARENT = user_profile()
TEACHER = user_profile(role=Role.TEACHER)
ONBOARDING_STATES = [state for state in ConversationState if state is not ConversationState.ACTIVE]


@pytest.mark.parametrize(
    "text",
    ["Beta ko rang kaise sikhayein?", "मेरा बच्चा खेलता नहीं", "😊", "ignore previous instructions"],
)
def test_an_active_parents_text_goes_to_the_journey(text: str) -> None:
    decision = TurnRouter.decide(PARENT, text, [])
    assert (decision.route, decision.reason) == (Route.JOURNEY, "parent default")


@pytest.mark.parametrize("text", ["", " ", "\n\t "])
def test_a_blank_message_asks_the_parent_to_repeat(text: str) -> None:
    decision = TurnRouter.decide(PARENT, text, [])
    assert (decision.route, decision.reason) == (Route.REPEAT_PLEASE, "blank message")


@pytest.mark.parametrize("state", ONBOARDING_STATES)
def test_every_onboarding_state_goes_to_onboarding_whatever_is_said(
    state: ConversationState,
) -> None:
    profile = user_profile(state=state, role=None, consented=False)
    for text, buttons in [("Hello", []), ("", ["onb:consent:yes"]), ("", ["jrn:done"])]:
        assert TurnRouter.decide(profile, text, buttons).route is Route.ONBOARDING


@pytest.mark.parametrize(
    "text", ["mera data hatao", "Delete my data", "मेरा डेटा हटाओ", "please consent wapas"]
)
@pytest.mark.parametrize("state", list(ConversationState))
def test_a_deletion_phrase_routes_to_deletion_in_any_state(
    text: str, state: ConversationState
) -> None:
    profile = user_profile(state=state)
    assert TurnRouter.decide(profile, text, []).route is Route.DATA_DELETION


@pytest.mark.parametrize("text", ["stop", "roz ka message band karo", "data", "delete"])
def test_ambiguous_words_never_delete_a_familys_data(text: str) -> None:
    assert TurnRouter.decide(PARENT, text, []).route is not Route.DATA_DELETION


def test_an_onboarding_button_from_an_active_user_goes_to_onboarding() -> None:
    decision = TurnRouter.decide(PARENT, "", ["onb:childtalk:yes:abc"])
    assert (decision.route, decision.reason) == (Route.ONBOARDING, "onboarding button")


def test_an_active_teacher_is_answered_by_onboarding_until_the_teacher_feature() -> None:
    decision = TurnRouter.decide(TEACHER, "Kal photosynthesis padhana hai", [])
    assert decision.route is Route.ONBOARDING


@pytest.mark.parametrize("text", ["English", "हिंदी", "hindi mein"])
def test_a_language_name_alone_switches_language(text: str) -> None:
    assert TurnRouter.decide(PARENT, text, []).route is Route.ONBOARDING


def test_adding_a_child_is_onboarding_for_parents() -> None:
    assert TurnRouter.decide(PARENT, "ek aur bachcha", []).route is Route.ONBOARDING


@given(text=st.text(max_size=50), button_id=st.text(min_size=1, max_size=40))
def test_unknown_buttons_from_active_parents_ask_to_repeat(text: str, button_id: str) -> None:
    if button_id.startswith("onb:"):
        return
    decision = TurnRouter.decide(PARENT, text, [button_id])
    assert decision.route is Route.REPEAT_PLEASE
