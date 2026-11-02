"""TurnRouter: which layer handles a turn (s05 §4.4; s08 §4.6; MVP rules, mvp-scope §4.3).

Deterministic: no model call. Rules are added, complete, by the step that builds what they route
to: S8 onboarding and deletion, S10b the `jrn:`/`nudge:` buttons and child talk, S10 the teacher
router. Safety runs before the routed layer, so crisis and blocked messages never reach
onboarding.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from app.domain.enums import ConversationState, Role, Route
from app.domain.models.learner import Learner
from app.domain.models.routing import RouteDecision
from app.domain.models.turn import UserProfile
from app.domain.rules.child_session_rules import ChildSessionRules
from app.domain.rules.onboarding_answer_parser import OnboardingAnswerParser
from app.domain.rules.phrase_finder import PhraseFinder

ONBOARDING_BUTTON_PREFIX: Final = "onb:"
JOURNEY_BUTTON_PREFIX: Final = "jrn:"
NUDGE_BUTTON_PREFIX: Final = "nudge:"
ROADMAP_BUTTON_PREFIX: Final = "rm:"
EXPOSURE_BUTTON_PREFIX: Final = "exp:"
DASHBOARD_WORDS: Final = ("dashboard", "डैशबोर्ड", "mera dashboard", "my dashboard")
"""A teacher's whole message asking for their district's students (s13 §4.9)."""
ROADMAP_PHRASES: Final = (
    "plan banao", "plan bana do", "plan bata", "mera plan", "naya plan", "roadmap", "make a plan",
    "my plan", "new plan", "योजना बनाओ", "प्लान बनाओ", "मेरा प्लान", "नया प्लान",
)  # fmt: skip
"""A student asking for (or to see) a plan, s12 §4.6. "plan" alone is too common to route on."""
NOT_A_PLAN_REQUEST: Final = (
    "plan tha", "plan thi", "plan was", "plan nahi chahiye", "plan nahi chahta", "no plan",
    "don't want a plan", "प्लान था", "प्लान नहीं चाहिए",
)  # fmt: skip
"""A plan that was ("mera plan tha doctor banne ka") or isn't wanted: not a plan request, so the
student intent reader decides (critic review §8, 2026-11-01)."""


@dataclass(frozen=True, slots=True)
class TurnFacts:
    """What the router knows about the turn besides its words and buttons. `has_photo`: a
    parent's photo with no words is a report for the journey, not a blank message (s10b §4.14)."""

    learners: Sequence[Learner] = ()
    child_session_open: bool = False
    has_photo: bool = False


NO_FACTS: Final = TurnFacts()


class TurnRouter:
    @staticmethod
    def decide(  # noqa: PLR0911  # one return per routing rule, in s08 §4.6's order
        profile: UserProfile,
        user_text: str,
        interactive_ids: Sequence[str],
        facts: TurnFacts = NO_FACTS,
    ) -> RouteDecision:
        """The account-level rules first (s08 §4.6), then the role's own (§ below)."""
        if facts.child_session_open:
            # Rule 1a (C13): a child is talking. Nothing they send reaches deletion or settings.
            return _to(Route.CHILD_TALK, "open child session")
        if not interactive_ids and TurnRouter._asks_for_deletion(profile, user_text):
            return _to(Route.DATA_DELETION, "deletion phrase")
        if profile.state is not ConversationState.ACTIVE:
            return _to(Route.ONBOARDING, f"state {profile.state.value}")
        if profile.role is Role.PARENT and ChildSessionRules.asks_to_start(
            user_text, interactive_ids, facts.learners
        ):
            return _to(Route.CHILD_TALK, "child starts talking")  # rule 6a
        if any(button.startswith(ONBOARDING_BUTTON_PREFIX) for button in interactive_ids):
            return _to(Route.ONBOARDING, "onboarding button")
        if OnboardingAnswerParser.language_named(user_text) is not None and not interactive_ids:
            return _to(Route.ONBOARDING, "language switch")
        match profile.role:
            case Role.STUDENT:
                return TurnRouter._student(user_text, interactive_ids)
            case Role.TEACHER:
                return TurnRouter._teacher(user_text, interactive_ids)
            case _:
                return TurnRouter._parent(user_text, interactive_ids, facts)

    @staticmethod
    def _asks_for_deletion(profile: UserProfile, user_text: str) -> bool:
        """A parent in the journey: only a short request on its own goes straight to deletion;
        a longer message is read by the intent model, which offers deletion if that's what it
        asks ("phone ka data delete ho gaya, khoj bhejo" isn't). Everyone else: any deletion
        phrase (owner, 2026-11-01)."""
        in_journey = profile.role is Role.PARENT and profile.state is ConversationState.ACTIVE
        if in_journey:
            return OnboardingAnswerParser.asks_only_for_deletion(user_text)
        return OnboardingAnswerParser.asks_for_deletion(user_text)

    @staticmethod
    def _parent(user_text: str, interactive_ids: Sequence[str], facts: TurnFacts) -> RouteDecision:
        if any(
            button.startswith((JOURNEY_BUTTON_PREFIX, NUDGE_BUTTON_PREFIX))
            for button in interactive_ids
        ):
            return _to(Route.JOURNEY, "journey button")
        if interactive_ids:
            # No other button prefix is routed; ids are never passed to a model (s05 rule 13).
            return _to(Route.REPEAT_PLEASE, "unknown interactive id")
        if facts.has_photo and not user_text.strip():
            return _to(Route.JOURNEY, "parent photo")
        if not user_text.strip():
            return _to(Route.REPEAT_PLEASE, "blank message")
        if OnboardingAnswerParser.adds_a_child_with_age(user_text):
            return _to(Route.ONBOARDING, "new child with age")  # added at once (2026-11-02)
        return _to(Route.JOURNEY, "parent default")

    @staticmethod
    def _teacher(user_text: str, interactive_ids: Sequence[str]) -> RouteDecision:
        """s10 §4.7: `exp:` buttons and any classroom message → EXPOSURE."""
        if any(button.startswith(EXPOSURE_BUTTON_PREFIX) for button in interactive_ids):
            return _to(Route.EXPOSURE, "exposure button")
        if interactive_ids:
            return _to(Route.REPEAT_PLEASE, "unknown interactive id")
        if not user_text.strip():
            return _to(Route.REPEAT_PLEASE, "blank message")
        if PhraseFinder.is_exactly(user_text, DASHBOARD_WORDS):
            return _to(Route.DASHBOARD_LINK, "dashboard asked for")
        return _to(Route.EXPOSURE, "teacher default")

    @staticmethod
    def _student(user_text: str, interactive_ids: Sequence[str]) -> RouteDecision:
        """s12 §4.6: `rm:` buttons and plan requests → ROADMAP; any other question → MENTOR."""
        if any(button.startswith(ROADMAP_BUTTON_PREFIX) for button in interactive_ids):
            return _to(Route.ROADMAP, "roadmap button")
        if interactive_ids:
            return _to(Route.REPEAT_PLEASE, "unknown interactive id")
        if not user_text.strip():
            return _to(Route.REPEAT_PLEASE, "blank message")
        not_a_request = PhraseFinder.contains_any(user_text, NOT_A_PLAN_REQUEST)
        if not not_a_request and PhraseFinder.contains_any(user_text, ROADMAP_PHRASES):
            return _to(Route.ROADMAP, "plan asked for")
        return _to(Route.MENTOR, "student default")


def _to(route: Route, reason: str) -> RouteDecision:
    return RouteDecision(route=route, mode_switch=None, reason=reason)
