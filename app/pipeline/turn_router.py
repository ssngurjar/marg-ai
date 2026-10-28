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
ROADMAP_PHRASES: Final = (
    "plan banao", "plan bana do", "plan bata", "mera plan", "naya plan", "roadmap", "make a plan",
    "my plan", "new plan", "योजना बनाओ", "प्लान बनाओ", "मेरा प्लान", "नया प्लान",
)  # fmt: skip
"""A student asking for (or to see) a plan, s12 §4.6. "plan" alone is too common to route on."""


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
        if not interactive_ids and OnboardingAnswerParser.asks_for_deletion(user_text):
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
                if interactive_ids:
                    return _to(Route.REPEAT_PLEASE, "unknown interactive id")
                return _to(Route.ONBOARDING, "teacher before the teacher feature")
            case _:
                return TurnRouter._parent(user_text, interactive_ids, facts)

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
        if OnboardingAnswerParser.asks_to_add_child(user_text):
            return _to(Route.ONBOARDING, "add a child")
        if facts.has_photo and not user_text.strip():
            return _to(Route.JOURNEY, "parent photo")
        if not user_text.strip():
            return _to(Route.REPEAT_PLEASE, "blank message")
        return _to(Route.JOURNEY, "parent default")

    @staticmethod
    def _student(user_text: str, interactive_ids: Sequence[str]) -> RouteDecision:
        """s12 §4.6: `rm:` buttons and plan requests → ROADMAP; any other question → MENTOR."""
        if any(button.startswith(ROADMAP_BUTTON_PREFIX) for button in interactive_ids):
            return _to(Route.ROADMAP, "roadmap button")
        if interactive_ids:
            return _to(Route.REPEAT_PLEASE, "unknown interactive id")
        if not user_text.strip():
            return _to(Route.REPEAT_PLEASE, "blank message")
        if PhraseFinder.contains_any(user_text, ROADMAP_PHRASES):
            return _to(Route.ROADMAP, "plan asked for")
        return _to(Route.MENTOR, "student default")


def _to(route: Route, reason: str) -> RouteDecision:
    return RouteDecision(route=route, mode_switch=None, reason=reason)
