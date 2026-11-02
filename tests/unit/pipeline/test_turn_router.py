"""TurnRouter: deterministic routing, no model call (s05 §4.4, s08 §4.6)."""

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from app.domain.enums import ConversationState, Role, Route
from app.domain.models.turn import UserProfile
from app.pipeline.turn_router import TurnFacts, TurnRouter
from tests.support.child_talk import consented_child
from tests.support.turn_context import user_profile

pytestmark = pytest.mark.unit

PARENT = user_profile()
TEACHER = user_profile(role=Role.TEACHER)
STUDENT_PROFILE = user_profile(role=Role.STUDENT)
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


@pytest.mark.parametrize("text", ["", " ", "\n"])
def test_a_parents_photo_without_words_is_a_journey_report_not_a_blank(text: str) -> None:
    decision = TurnRouter.decide(PARENT, text, [], TurnFacts(has_photo=True))
    assert (decision.route, decision.reason) == (Route.JOURNEY, "parent photo")


def test_a_photo_never_skips_onboarding_or_a_childs_session() -> None:
    onboarding = user_profile(state=ConversationState.NEW, role=None, consented=False)
    assert (
        TurnRouter.decide(onboarding, "", [], TurnFacts(has_photo=True)).route is Route.ONBOARDING
    )
    assert (
        TurnRouter.decide(TEACHER, "", [], TurnFacts(has_photo=True)).route is Route.REPEAT_PLEASE
    )
    child_talking = TurnRouter.decide(
        PARENT, "", [], TurnFacts(has_photo=True, child_session_open=True)
    )
    assert child_talking.route is Route.CHILD_TALK


def test_a_captioned_photo_is_routed_by_its_words() -> None:
    decision = TurnRouter.decide(PARENT, "mera data hatao", [], TurnFacts(has_photo=True))
    assert decision.route is Route.DATA_DELETION


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


def test_an_active_teachers_classroom_message_goes_to_exposure() -> None:
    decision = TurnRouter.decide(TEACHER, "Kal photosynthesis padhana hai", [])
    assert (decision.route, decision.reason) == (Route.EXPOSURE, "teacher default")


@pytest.mark.parametrize("button", ["exp:more", "exp:new"])
def test_exposure_buttons_go_to_exposure_for_teachers_only(button: str) -> None:
    assert TurnRouter.decide(TEACHER, "", [button]).route is Route.EXPOSURE
    assert TurnRouter.decide(STUDENT_PROFILE, "", [button]).route is Route.REPEAT_PLEASE
    assert TurnRouter.decide(PARENT, "", [button]).route is Route.REPEAT_PLEASE


def test_a_teachers_blank_message_or_unknown_button_asks_again() -> None:
    assert TurnRouter.decide(TEACHER, "  ", []).route is Route.REPEAT_PLEASE
    assert TurnRouter.decide(TEACHER, "", ["rm:create"]).route is Route.REPEAT_PLEASE


@pytest.mark.parametrize("text", ["English", "हिंदी", "hindi mein"])
def test_a_language_name_alone_switches_language(text: str) -> None:
    assert TurnRouter.decide(PARENT, text, []).route is Route.ONBOARDING


@pytest.mark.parametrize(
    "text",
    [
        "ek aur bachcha",
        "my son keeps hitting another child at school",  # a worry, not a request (2026-11-01)
        "beti doosre bachche ke liye khilona chhin leti hai",
    ],
)
def test_a_parents_words_about_another_child_go_to_the_journey_to_be_read(text: str) -> None:
    # the intent model tells "add my son too" from a worry; the add-child button still works
    assert TurnRouter.decide(PARENT, text, []).route is Route.JOURNEY
    assert TurnRouter.decide(PARENT, "", ["onb:add-child"]).route is Route.ONBOARDING


@pytest.mark.parametrize(
    "text",
    [
        "phone ka data delete ho gaya, khoj phir se bhejo",
        "mobile data hatao kaise karte hain",
        "bachche ka data delete karo please",
    ],
)
def test_a_parents_longer_message_with_a_deletion_phrase_is_read_not_routed(text: str) -> None:
    assert TurnRouter.decide(PARENT, text, []).route is Route.JOURNEY


@pytest.mark.parametrize("role", [Role.STUDENT, Role.TEACHER])
def test_for_students_and_teachers_any_deletion_phrase_still_deletes(role: Role) -> None:
    profile = user_profile(role=role)
    text = "please delete my data, I don't want to use this anymore"
    assert TurnRouter.decide(profile, text, []).route is Route.DATA_DELETION


KNOWN_PREFIXES = ("onb:", "jrn:", "nudge:", "kid:")


@given(text=st.text(max_size=50), button_id=st.text(min_size=1, max_size=40))
def test_unknown_buttons_from_active_parents_ask_to_repeat(text: str, button_id: str) -> None:
    assume(not button_id.startswith(KNOWN_PREFIXES))  # those are routed (test below)
    decision = TurnRouter.decide(PARENT, text, [button_id])
    assert decision.route is Route.REPEAT_PLEASE


@pytest.mark.parametrize(
    ("button_id", "route"), [("jrn:", Route.JOURNEY), ("nudge:", Route.JOURNEY)]
)
def test_a_bare_known_prefix_still_goes_to_its_layer(button_id: str, route: Route) -> None:
    """Hypothesis found "jrn:" (2026-10-28): the prefix alone is a journey button, and the
    journey answers an id it doesn't know."""
    assert TurnRouter.decide(PARENT, "", [button_id]).route is route


# --- child talk (C13, rules 1a and 6a) -----------------------------------------------------------

MUNNI = consented_child()


@pytest.mark.parametrize(
    ("text", "buttons"),
    [
        ("mera data hatao", []),
        ("delete my data", []),
        ("", ["onb:delete:yes"]),
        ("", ["jrn:other"]),
        ("English", []),
        ("chaand kyun chamakta hai?", []),
    ],
)
def test_inside_a_child_session_everything_goes_to_child_talk(
    text: str, buttons: list[str]
) -> None:
    decision = TurnRouter.decide(
        PARENT, text, buttons, TurnFacts(learners=[MUNNI], child_session_open=True)
    )
    assert decision.route is Route.CHILD_TALK


@pytest.mark.parametrize(
    ("text", "buttons"),
    [
        ("", ["kid:start"]),
        ("", [f"kid:start:{MUNNI.id}"]),
        ("Main Munni hoon", []),
        ("mai bacha hun", []),  # owner's field test, 2026-11-01: the copy tells them to say it
        ("मैं बच्ची हूँ", []),
    ],
)
def test_a_parent_account_starts_child_talk_with_the_button_or_a_name(
    text: str, buttons: list[str]
) -> None:
    decision = TurnRouter.decide(PARENT, text, buttons, TurnFacts(learners=[MUNNI]))
    assert decision.route is Route.CHILD_TALK


def test_a_teacher_cant_start_child_talk() -> None:
    assert TurnRouter.decide(TEACHER, "", ["kid:start"], TurnFacts(learners=[MUNNI])).route is not (
        Route.CHILD_TALK
    )


def test_child_talk_never_starts_before_onboarding_is_done() -> None:
    onboarding = user_profile(state=ConversationState.AWAITING_CONSENT, role=None, consented=False)
    decision = TurnRouter.decide(onboarding, "Main Munni hoon", [], TurnFacts(learners=[MUNNI]))
    assert decision.route is Route.ONBOARDING


@pytest.mark.parametrize("button", ["nudge:08", "nudge:18", "nudge:off"])
def test_a_parents_nudge_button_goes_to_the_journey(button: str) -> None:
    assert TurnRouter.decide(PARENT, "", [button]).route is Route.JOURNEY


def test_a_teachers_nudge_button_is_not_routed_to_the_journey() -> None:
    assert TurnRouter.decide(TEACHER, "", ["nudge:08"]).route is not Route.JOURNEY


# --- students (s12 §4.6) -------------------------------------------------------------------------

STUDENT = user_profile(role=Role.STUDENT)


@pytest.mark.parametrize(
    "text",
    [
        "10vi ke baad kya karun?",
        "क्लास 8 में कोई स्कॉलरशिप मिलती है क्या",
        "mujhe ek gaana sunao",
        "plan",
    ],
)
def test_a_students_message_goes_to_the_mentor(text: str) -> None:
    decision = TurnRouter.decide(STUDENT, text, [])
    assert (decision.route, decision.reason) == (Route.MENTOR, "student default")


@pytest.mark.parametrize(
    "text",
    ["doctor banna hai, plan bana do", "mera plan dikhao", "naya plan", "नया प्लान", "roadmap"],
)
def test_a_plan_request_goes_to_the_roadmap(text: str) -> None:
    assert TurnRouter.decide(STUDENT, text, []).route is Route.ROADMAP


@pytest.mark.parametrize(
    "text",
    [
        "mera plan tha doctor banne ka par marks kam aaye, ab kya karun",
        "my plan was to join the army but I failed",
        "mujhe plan nahi chahiye, bas batao nurse kitna kamati hai",
        "मेरा प्लान था पुलिस में जाने का",
    ],
)
def test_a_plan_that_was_or_isnt_wanted_is_not_a_plan_request(text: str) -> None:
    # critic review §8, 2026-11-01: "mera plan tha…" made a new plan by words
    decision = TurnRouter.decide(STUDENT, text, [])
    assert (decision.route, decision.reason) == (Route.MENTOR, "student default")


def test_the_plan_button_goes_to_the_roadmap_and_other_buttons_ask_again() -> None:
    assert TurnRouter.decide(STUDENT, "", ["rm:create"]).route is Route.ROADMAP
    assert TurnRouter.decide(STUDENT, "", ["jrn:today"]).route is Route.REPEAT_PLEASE
    assert TurnRouter.decide(PARENT, "", ["rm:create"]).route is Route.REPEAT_PLEASE


@pytest.mark.parametrize("text", ["", "   "])
def test_a_students_blank_message_asks_again(text: str) -> None:
    assert TurnRouter.decide(STUDENT, text, []).route is Route.REPEAT_PLEASE


def test_a_student_can_still_delete_their_data_and_switch_language() -> None:
    assert TurnRouter.decide(STUDENT, "mera data hatao", []).route is Route.DATA_DELETION
    assert TurnRouter.decide(STUDENT, "english", []).route is Route.ONBOARDING


@pytest.mark.parametrize("text", ["dashboard", "Dashboard", "डैशबोर्ड", "my dashboard"])
def test_a_teacher_asking_for_the_dashboard_gets_a_link(text: str) -> None:
    assert TurnRouter.decide(TEACHER, text, []).route is Route.DASHBOARD_LINK


@pytest.mark.parametrize(
    ("profile", "text"), [("parent", "dashboard"), ("teacher", "dashboard kya hai")]
)
def test_only_a_teachers_whole_message_is_a_dashboard_request(profile: str, text: str) -> None:
    who = PARENT if profile == "parent" else TEACHER
    assert TurnRouter.decide(who, text, []).route is not Route.DASHBOARD_LINK


@pytest.mark.parametrize(
    "text",
    ["Another child Riya, 7", "ek aur bachcha hai Golu 4 saal ka", "एक और बच्चा मुन्नी 5 साल"],
)
def test_another_child_with_its_age_goes_to_onboarding_to_be_added(text: str) -> None:
    # second field test, 2026-11-02: the name and age had to be typed again after a button
    decision = TurnRouter.decide(PARENT, text, [])
    assert decision.route is Route.ONBOARDING
    assert decision.reason == "new child with age"


@pytest.mark.parametrize(
    "text",
    ["my son, 6, keeps hitting another child at school", "doosre bachche ke liye khoj, 5 saal"],
)
def test_an_age_in_words_about_another_child_still_goes_to_the_journey(text: str) -> None:
    assert TurnRouter.decide(PARENT, text, []).route is Route.JOURNEY


@pytest.mark.parametrize("profile", [TEACHER, STUDENT_PROFILE], ids=["teacher", "student"])
def test_only_a_parent_adds_a_child_by_words(profile: UserProfile) -> None:
    assert TurnRouter.decide(profile, "another child Riya 7", []).route is not Route.ONBOARDING
