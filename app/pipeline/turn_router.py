"""TurnRouter: which layer handles a turn (s05 §4.4; MVP rules, mvp-scope §4.3).

Deterministic for parents: no model call. Rules are added, complete, by the step that builds
what they route to (s05 §4.4): S8 adds onboarding and deletion, S10b the `jrn:`/`nudge:` buttons
and child talk, S10 the teacher LLM router. Until S8, everyone who reaches the pipeline is
treated as an active parent.
"""

from collections.abc import Sequence

from app.domain.enums import Route
from app.domain.models.routing import RouteDecision


class TurnRouter:
    @staticmethod
    def decide(user_text: str, interactive_ids: Sequence[str]) -> RouteDecision:
        if interactive_ids:
            # No button prefix is routed yet; ids are never passed to a model (s05 rule 13).
            return RouteDecision(
                route=Route.REPEAT_PLEASE, mode_switch=None, reason="unknown interactive id"
            )
        if not user_text.strip():
            return RouteDecision(
                route=Route.REPEAT_PLEASE, mode_switch=None, reason="blank message"
            )
        return RouteDecision(route=Route.JOURNEY, mode_switch=None, reason="parent default")
