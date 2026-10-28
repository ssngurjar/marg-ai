"""TurnCapture: what one eval turn did, from the pipeline's observer and the database (s15 §4.2).

The database keeps what production needs: the route, the reply text, every step with its cost.
It deliberately doesn't keep the safety verdicts or the reply before it was sealed, so the eval
passes this observer to the turn and reads them as the steps finish. TurnRecord joins the two,
plus the text that went to text-to-speech and the sources behind each citation.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.domain.enums import FixedReplyKind, Language, Route, StepName
from app.domain.models.base import TurnId
from app.domain.models.reply import CanonicalReply, Citation
from app.domain.models.safety import SafetyVerdict
from app.domain.models.usage import StepUsage
from app.layers.layer_result import LayerResult
from app.pipeline.step_models import StepFailure, StepSuccess
from app.store.repositories.eval_repository import EvalTurnSnapshot, SourceText


@dataclass(frozen=True, slots=True)
class TurnRecord:
    snapshot: EvalTurnSnapshot
    safety_in: SafetyVerdict | None
    safety_out: SafetyVerdict | None
    generated: CanonicalReply | None  # the layer's reply, before the output check
    spoken_texts: list[str]  # exactly what went to text-to-speech
    sources: list[SourceText]  # the full text behind each citation
    later_turns: list[EvalTurnSnapshot]  # started by the system after this one (a khoj card)
    media_left: int  # this user's media rows once the turn was over
    card_prompts: list[str]  # what a khoj card's picture was asked to show

    @property
    def turn_id(self) -> TurnId:
        return self.snapshot.turn_id

    @property
    def route(self) -> Route | None:
        return self.snapshot.route

    @property
    def fixed_reply(self) -> FixedReplyKind | None:
        kind = self.snapshot.fixed_reply_kind
        return FixedReplyKind(kind) if kind else None

    @property
    def reply_text(self) -> str:
        return self.snapshot.reply_text or ""

    @property
    def reply_register(self) -> Language | None:
        return self.snapshot.reply_register

    @property
    def citations(self) -> list[Citation]:
        return list(self.generated.citations) if self.generated is not None else []

    @property
    def generated_text(self) -> bool:
        """A layer wrote this reply (a fixed reply is reviewed copy, never generated)."""
        return any(step.step == StepName.GENERATE.value for step in self.snapshot.steps)

    @property
    def cost_usd(self) -> Decimal:
        return sum((step.cost_usd for step in self.snapshot.steps), Decimal(0))


@dataclass(slots=True)
class TurnCapture:
    """The observer for one turn (contracts §3 TurnObserver)."""

    safety_in: SafetyVerdict | None = None
    safety_out: SafetyVerdict | None = None
    generated: CanonicalReply | None = None

    async def on_step(
        self,
        turn_id: TurnId,
        step: StepName,
        result: StepSuccess[object] | StepFailure,
        usage: StepUsage | None,
        duration_ms: int,
    ) -> None:
        if isinstance(result, StepFailure):
            return  # failed steps are in turn_steps, which the snapshot reads
        output = result.output
        if step is StepName.SAFETY_IN and isinstance(output, SafetyVerdict):
            self.safety_in = output
        elif step is StepName.SAFETY_OUT and isinstance(output, SafetyVerdict):
            self.safety_out = output
        elif step is StepName.GENERATE:
            self.generated = _reply_of(output)


def _reply_of(output: object) -> CanonicalReply | None:
    """GENERATE reports a layer's whole result, or (for a parent's question) the reply alone."""
    if isinstance(output, LayerResult):
        return output.reply
    if isinstance(output, CanonicalReply):
        return output
    return None
