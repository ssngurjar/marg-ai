"""A stand-in for S5's `run_turn`: scripted outcomes built through the real sealed path."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.domain.enums import FixedReplyKind, Language, Route
from app.domain.models.reply import LocalisedReply, ReplyButton
from app.domain.models.turn import TurnContext
from app.pipeline.reply_parts_builder import ReplyPartsBuilder
from app.pipeline.step_models import StepFailure, TurnOutcome
from app.pipeline.turn_protocols import StepRecorder, TurnObserver
from app.safety.safety_gate import SafetyGate


@dataclass(frozen=True, slots=True)
class ScriptedReply:
    text: str = "Theek hai, hum saath milke dekhte hain."
    route: Route = Route.JOURNEY
    fixed_kind: FixedReplyKind | None = None
    buttons: tuple[ReplyButton, ...] = ()
    first_failure: StepFailure | None = None


@dataclass
class FakeOrchestrator:
    """Callable like `run_turn`. Each call takes the next scripted reply (the last one repeats);
    `raise_times` makes the first N calls raise, like a bug in the pipeline."""

    replies: Sequence[ScriptedReply] = (ScriptedReply(),)
    raise_times: int = 0
    block: asyncio.Event | None = None  # when set, each call waits for it (a slow turn)
    contexts: list[TurnContext] = field(default_factory=list)
    called: asyncio.Event = field(default_factory=asyncio.Event)  # set on the first call
    gate: SafetyGate = field(default_factory=SafetyGate)

    async def __call__(
        self, ctx: TurnContext, recorder: StepRecorder, observer: TurnObserver
    ) -> TurnOutcome:
        self.contexts.append(ctx)
        self.called.set()
        if self.block is not None:
            await self.block.wait()
        if len(self.contexts) <= self.raise_times:
            raise RuntimeError("scripted pipeline bug")
        reply = self.replies[min(len(self.contexts) - 1, len(self.replies) - 1)]
        localised = LocalisedReply(
            text=reply.text,
            spoken_text=reply.text,
            reply_register=Language.HINGLISH,
            citations=[],
            buttons=list(reply.buttons),
        )
        # S5's classifier path doesn't exist yet, so tests seal every scripted reply through
        # clear_fixed. Only the fixed kind matters to the parts builder (CRISIS: text first).
        safe = self.gate.clear_fixed(localised, reply.fixed_kind or FixedReplyKind.HOLDING)
        user_text = " ".join(message.text or "" for message in ctx.messages).strip() or None
        return TurnOutcome(
            turn_id=ctx.turn_id,
            route=reply.route,
            delivery=ReplyPartsBuilder.build(safe, audio_blob_id=None),
            fixed_reply_kind=reply.fixed_kind,
            user_text=user_text,
            reply_text=safe.text,
            reply_register=safe.reply_register,
            prompt_versions={"fake": "1"},
            first_failure=reply.first_failure,
        )
