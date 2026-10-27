"""The turn pipeline's entry point (s05 §4.5).

S4 adds the production observer; S5 adds `run_turn`.
"""

from app.domain.enums import StepName
from app.domain.models.base import TurnId
from app.pipeline.step_models import StepFailure, StepSuccess, StepUsage


class NullTurnObserver:
    """The production observer: it records nothing (turn_steps already holds every step)."""

    async def on_step(
        self,
        turn_id: TurnId,
        step: StepName,
        result: StepSuccess[object] | StepFailure,
        usage: StepUsage | None,
        duration_ms: int,
    ) -> None:
        return None
