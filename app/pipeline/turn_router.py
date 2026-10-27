"""TurnRouter: which layer handles a turn (s05 §4.4; s08 §4.6; MVP rules, mvp-scope §4.3).

Deterministic: no model call. Rules are added, complete, by the step that builds what they route
to: S8 onboarding and deletion, S10b the `jrn:`/`nudge:` buttons and child talk, S10 the teacher
router. Safety runs before the routed layer, so crisis and blocked messages never reach
onboarding.
"""

from collections.abc import Sequence
from typing import Final

from app.domain.enums import ConversationState, Role, Route
from app.domain.models.routing import RouteDecision
from app.domain.models.turn import UserProfile
from app.domain.rules.onboarding_answer_parser import OnboardingAnswerParser

ONBOARDING_BUTTON_PREFIX: Final = "onb:"
JOURNEY_BUTTON_PREFIX: Final = "jrn:"


class TurnRouter:
    @staticmethod
    def decide(  # noqa: PLR0911  # one return per routing rule, in s08 §4.6's order
        profile: UserProfile, user_text: str, interactive_ids: Sequence[str]
    ) -> RouteDecision:
        if not interactive_ids and OnboardingAnswerParser.asks_for_deletion(user_text):
            return _to(Route.DATA_DELETION, "deletion phrase")
        if profile.state is not ConversationState.ACTIVE:
            return _to(Route.ONBOARDING, f"state {profile.state.value}")
        if any(button.startswith(ONBOARDING_BUTTON_PREFIX) for button in interactive_ids):
            return _to(Route.ONBOARDING, "onboarding button")
        if profile.role is Role.PARENT and any(
            button.startswith(JOURNEY_BUTTON_PREFIX) for button in interactive_ids
        ):
            return _to(Route.JOURNEY, "journey button")
        if interactive_ids:
            # No other button prefix is routed yet; ids are never passed to a model (s05 rule 13).
            return _to(Route.REPEAT_PLEASE, "unknown interactive id")
        if profile.role is Role.TEACHER:
            return _to(Route.ONBOARDING, "teacher before the teacher feature")
        if OnboardingAnswerParser.language_named(user_text) is not None:
            return _to(Route.ONBOARDING, "language switch")
        if profile.role is Role.PARENT and OnboardingAnswerParser.asks_to_add_child(user_text):
            return _to(Route.ONBOARDING, "add a child")
        if not user_text.strip():
            return _to(Route.REPEAT_PLEASE, "blank message")
        return _to(Route.JOURNEY, "parent default")


def _to(route: Route, reason: str) -> RouteDecision:
    return RouteDecision(route=route, mode_switch=None, reason=reason)
