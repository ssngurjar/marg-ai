"""Orchestrator: one turn from the user's messages to a sealed reply (s05 §4.5, mvp-scope §4.2).

    A. user text            text messages joined; audio and images aren't understood before S6/S10b
    B. route ‖ safety_in ‖ generate
                            generation starts with the safety check, and its result is used ONLY
                            if safety_in returns ALLOW; otherwise it's cancelled, unread (C3a)
    C. translate            SKIPPED: the layer wrote in the user's register (C3c)
    D. safety_out           the generated reply is sealed only if Llama Guard allows it
    E. parts                ReplyPartsBuilder → TurnOutcome

Onboarding and deletion turns (s08) run safety_in, then the onboarding layer, whose reply is
reviewed fixed copy (sealed without a classifier call) and whose writes ride on the outcome.

Every turn ends with a reply. A provider failure becomes a fixed reply (HOLDING when a safety
check fails: fail closed); only a programming error raises, which the worker treats as a crashed
turn. Every step is recorded; a recording failure is logged and never takes the reply down.
"""

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar, Final, Literal

from app.core.clock import Clock
from app.core.errors import DomainError, ProviderError, SafetyUnavailable, StoreError
from app.core.logging import get_logger
from app.domain.enums import (
    FixedReplyKind,
    FixedReplyVariant,
    Language,
    MessageKind,
    Route,
    SafetyDecision,
    StepName,
    StepOutcome,
)
from app.domain.models.reply import LocalisedReply
from app.domain.models.safety import SafetyVerdict
from app.domain.models.turn import TurnContext
from app.domain.models.usage import StepUsage
from app.domain.rules.register_detector import RegisterDetector
from app.layers.layer_result import LayerResult
from app.layers.onboarding_layer import OnboardingLayer, OnboardingResult
from app.layers.parent_question_layer import ParentQuestionLayer
from app.pipeline.failure_policy import FailurePolicy
from app.pipeline.fixed_reply_service import FixedReplyService
from app.pipeline.reply_parts_builder import ReplyPartsBuilder
from app.pipeline.step_models import StepFailure, StepSuccess, TurnOutcome
from app.pipeline.turn_protocols import StepRecorder, TurnObserver
from app.pipeline.turn_router import TurnRouter
from app.safety.safety_gate import InputCheck, OutputCheck, SafetyGate

FALLBACK_REGISTER: Final = Language.HINGLISH
"""Until onboarding records a language (S8), a message with no letters is answered in Hinglish."""

logger = get_logger(__name__)

type SuccessOutcome = Literal[StepOutcome.OK, StepOutcome.DEGRADED]


@dataclass(frozen=True, slots=True)
class OrchestratorSettings:
    turn_budget: timedelta  # TURN_BUDGET_S
    safety_in_timeout: timedelta
    generate_timeout: timedelta
    safety_out_timeout: timedelta


@dataclass(frozen=True, slots=True)
class PipelineSteps:
    gate: SafetyGate
    parent_questions: ParentQuestionLayer
    onboarding: OnboardingLayer
    clock: Clock


@dataclass(frozen=True, slots=True)
class _FixedChoice:
    kind: FixedReplyKind
    variant: FixedReplyVariant
    route: Route


@dataclass(frozen=True, slots=True)
class _StepRecord:
    step: StepName
    started: datetime
    output: object
    usage: StepUsage | None
    detail: str | None
    decision: SafetyDecision | None = None
    outcome: SuccessOutcome = StepOutcome.OK


class Orchestrator:
    DELIVERY_RESERVE: ClassVar[timedelta] = timedelta(seconds=1)
    """Kept back from every step's budget so a fixed reply always has time to go out."""

    def __init__(self, steps: PipelineSteps, settings: OrchestratorSettings) -> None:
        self.steps = steps
        self.settings = settings

    async def run_turn(
        self, ctx: TurnContext, recorder: StepRecorder, observer: TurnObserver
    ) -> TurnOutcome:
        return await _Turn(ctx, recorder, observer, self).run()


class _Turn:
    """The state of one run_turn call. Never shared between turns."""

    def __init__(
        self,
        ctx: TurnContext,
        recorder: StepRecorder,
        observer: TurnObserver,
        orchestrator: Orchestrator,
    ) -> None:
        self.ctx = ctx
        self.recorder = recorder
        self.observer = observer
        self.steps = orchestrator.steps
        self.settings = orchestrator.settings
        self.deadline = self.steps.clock.now() + self.settings.turn_budget
        self.first_failure: StepFailure | None = None
        self.prompt_versions: dict[str, str] = {}
        self.user_text = ""
        self.register = FALLBACK_REGISTER

    async def run(self) -> TurnOutcome:
        interactive_ids, has_unsupported = self._read_messages()
        self.register = (
            RegisterDetector.detect(self.user_text)
            or self.ctx.profile.language
            or FALLBACK_REGISTER
        )
        if self.user_text:
            await self._safely(self.recorder.set_turn_text(self.ctx.turn_id, self.user_text))
        if not self.user_text and not interactive_ids and has_unsupported:
            return self._fixed(
                _FixedChoice(
                    FixedReplyKind.UNSUPPORTED_MEDIA, FixedReplyVariant.DEFAULT, Route.REPEAT_PLEASE
                )
            )
        routed_at = self.steps.clock.now()
        decision = TurnRouter.decide(self.ctx.profile, self.user_text, interactive_ids)
        await self._record(_StepRecord(StepName.ROUTE, routed_at, decision, None, decision.reason))
        await self._safely(self.recorder.set_turn_route(self.ctx.turn_id, decision.route))
        if decision.route is Route.REPEAT_PLEASE:
            return self._fixed(
                _FixedChoice(
                    FixedReplyKind.REPEAT_PLEASE, FixedReplyVariant.DEFAULT, decision.route
                )
            )
        if decision.route in {Route.ONBOARDING, Route.DATA_DELETION}:
            return await self._onboarding(decision.route, interactive_ids)
        return await self._journey()

    async def _onboarding(self, route: Route, interactive_ids: list[str]) -> TurnOutcome:
        """safety_in on what the user typed (button ids are ours), then the onboarding layer."""
        started = self.steps.clock.now()
        if self.user_text:
            try:
                input_check = await self._bounded(
                    self.steps.gate.check_input(self.user_text), self.settings.safety_in_timeout
                )
            except (SafetyUnavailable, TimeoutError) as error:
                return await self._failed(StepName.SAFETY_IN, started, error)
            await self._record(self._input_record(started, input_check))
            if input_check.verdict.decision is not SafetyDecision.ALLOW:
                return self._fixed(self._refusal_for(input_check))
        started = self.steps.clock.now()
        try:
            result = await self._bounded(
                self.steps.onboarding.handle(
                    self.ctx, self.user_text, interactive_ids, self.steps.clock.now()
                ),
                self.settings.generate_timeout,
            )
        except (DomainError, TimeoutError) as error:
            return await self._failed(StepName.GENERATE, started, error)
        self.prompt_versions = dict(result.prompt_versions)
        await self._record(
            _StepRecord(
                StepName.GENERATE,
                started,
                result.reply,
                StepUsage.total(result.usages),
                result.degraded_reason,
                outcome=result.outcome,
            )
        )
        await self._record_skipped(StepName.TRANSLATE, "fixed onboarding copy")
        return self._onboarding_outcome(route, result)

    def _onboarding_outcome(self, route: Route, result: OnboardingResult) -> TurnOutcome:
        """Onboarding copy is reviewed fixed text: sealed without a classifier call (s07 §4.2)."""
        reply = result.reply
        kind = reply.fixed_kind or FixedReplyKind.ONBOARDING
        localised = LocalisedReply(
            text=reply.body,
            spoken_text=reply.spoken_text or reply.body,
            reply_register=reply.body_language,
            citations=reply.citations,
            buttons=reply.buttons,
        )
        safe = self.steps.gate.clear_fixed(localised, kind)
        return TurnOutcome(
            turn_id=self.ctx.turn_id,
            route=route,
            delivery=ReplyPartsBuilder.build(safe, audio_blob_id=None),
            fixed_reply_kind=kind,
            user_text=self.user_text or None,
            reply_text=safe.text,
            reply_register=safe.reply_register,
            prompt_versions=self.prompt_versions,
            first_failure=self.first_failure,
            writes=list(result.writes),
        )

    async def _journey(self) -> TurnOutcome:
        started = self.steps.clock.now()
        generation = asyncio.create_task(self._generate())
        try:
            input_check = await self._bounded(
                self.steps.gate.check_input(self.user_text), self.settings.safety_in_timeout
            )
        except (SafetyUnavailable, TimeoutError) as error:
            await self._discard(generation)
            return await self._failed(StepName.SAFETY_IN, started, error)
        await self._record(self._input_record(started, input_check))
        if input_check.verdict.decision is not SafetyDecision.ALLOW:
            await self._discard(generation)
            return self._fixed(self._refusal_for(input_check))
        try:
            layer_result = await generation
        except (ProviderError, TimeoutError) as error:
            return await self._failed(StepName.GENERATE, started, error)
        self.prompt_versions = dict(layer_result.prompt_versions)
        await self._record(
            _StepRecord(
                StepName.GENERATE,
                started,
                layer_result,
                StepUsage.total(layer_result.usages),
                layer_result.degraded_reason,
                outcome=layer_result.outcome,
            )
        )
        await self._record_skipped(StepName.TRANSLATE, "direct localisation (C3c)")
        return await self._check_and_seal(layer_result)

    async def _generate(self) -> LayerResult:
        """The layer call is made inside the task, so a task cancelled before it starts leaves
        no un-awaited coroutine behind."""
        return await self._bounded(
            self.steps.parent_questions.answer(self.ctx, self.user_text, self.register),
            self.settings.generate_timeout,
        )

    async def _check_and_seal(self, layer_result: LayerResult) -> TurnOutcome:
        reply = layer_result.reply
        localised = LocalisedReply(
            text=reply.body,
            spoken_text=reply.spoken_text or reply.body,
            reply_register=reply.body_language,
            citations=reply.citations,
            buttons=reply.buttons,
        )
        started = self.steps.clock.now()
        try:
            output_check = await self._bounded(
                self.steps.gate.check_output(localised, self.user_text),
                self.settings.safety_out_timeout,
            )
        except (SafetyUnavailable, TimeoutError) as error:
            return await self._failed(StepName.SAFETY_OUT, started, error)
        await self._record(self._output_record(started, output_check))
        if output_check.safe_reply is None:
            # Our own reply was flagged: a fixed redirect, and nothing generated goes out.
            return self._fixed(
                _FixedChoice(FixedReplyKind.REFUSE, FixedReplyVariant.GENERIC, Route.JOURNEY)
            )
        safe = output_check.safe_reply
        return TurnOutcome(
            turn_id=self.ctx.turn_id,
            route=Route.JOURNEY,
            delivery=ReplyPartsBuilder.build(safe, audio_blob_id=None),
            fixed_reply_kind=None,
            user_text=self.user_text,
            reply_text=safe.text,
            reply_register=safe.reply_register,
            prompt_versions=self.prompt_versions,
            first_failure=self.first_failure,
            writes=[],
        )

    # --- turn pieces -------------------------------------------------------------------------

    def _read_messages(self) -> tuple[list[str], bool]:
        """Sets the combined user text; returns interactive ids and whether media was sent."""
        texts: list[str] = []
        interactive_ids: list[str] = []
        has_unsupported = False
        for message in self.ctx.messages:
            if message.kind is MessageKind.TEXT and message.text and message.text.strip():
                texts.append(message.text.strip())
            elif message.kind is MessageKind.INTERACTIVE and message.interactive_reply_id:
                interactive_ids.append(message.interactive_reply_id)
            elif message.kind is not MessageKind.TEXT:  # AUDIO before S6, IMAGE before S10b
                has_unsupported = True
        self.user_text = "\n".join(texts)
        return interactive_ids, has_unsupported

    @staticmethod
    def _refusal_for(check: InputCheck) -> _FixedChoice:
        variant = check.variant or FixedReplyVariant.GENERAL
        if check.verdict.decision is SafetyDecision.CRISIS:
            return _FixedChoice(FixedReplyKind.CRISIS, variant, Route.CRISIS)
        return _FixedChoice(FixedReplyKind.REFUSE, variant, Route.REFUSE)

    async def _failed(self, step: StepName, started: datetime, error: BaseException) -> TurnOutcome:
        """Record the failure and answer with the step's fallback (s05 §4.5 table)."""
        failure = StepFailure(
            step=step,
            kind=FailurePolicy.kind_of(error),
            detail=type(error).__name__,  # never the message: it can quote generated text
            retryable=FailurePolicy.is_retryable(error),
        )
        if self.first_failure is None:
            self.first_failure = failure
        duration_ms = self._elapsed_ms(started)
        fallback = FailurePolicy.reply_for(step)
        await self._safely(
            self.recorder.record(
                turn_id=self.ctx.turn_id,
                step=step,
                outcome=StepOutcome.FAILED,
                started_at=started,
                duration_ms=duration_ms,
                usage=None,
                failure=failure,
                detail=f"fallback={fallback.value}",
            )
        )
        await self.observer.on_step(self.ctx.turn_id, step, failure, None, duration_ms)
        return self._fixed(_FixedChoice(fallback, FixedReplyVariant.DEFAULT, Route.JOURNEY))

    def _fixed(self, choice: _FixedChoice) -> TurnOutcome:
        """A reviewed fixed text, sealed without a classifier call (s07 §4.2)."""
        localised = FixedReplyService.localise(choice.kind, choice.variant, self.register)
        safe = self.steps.gate.clear_fixed(localised, choice.kind)
        return TurnOutcome(
            turn_id=self.ctx.turn_id,
            route=choice.route,
            delivery=ReplyPartsBuilder.build(safe, audio_blob_id=None),
            fixed_reply_kind=choice.kind,
            user_text=self.user_text or None,
            reply_text=safe.text,
            reply_register=safe.reply_register,
            prompt_versions=self.prompt_versions,
            first_failure=self.first_failure,
            writes=[],
        )

    async def _bounded[ResultT](self, work: Awaitable[ResultT], step_timeout: timedelta) -> ResultT:
        """Run `work` within min(step timeout, what's left of the turn minus the reserve)."""
        remaining = self.deadline - self.steps.clock.now() - Orchestrator.DELIVERY_RESERVE
        allowed = min(step_timeout, remaining).total_seconds()
        if allowed <= 0:
            if asyncio.iscoroutine(work):
                work.close()
            raise TimeoutError("turn budget exhausted")
        async with asyncio.timeout(allowed):
            return await work

    @staticmethod
    async def _discard(generation: "asyncio.Task[LayerResult]") -> None:
        """Cancel generation whose result may not be used; never read what it produced (C3a)."""
        generation.cancel()
        await asyncio.gather(generation, return_exceptions=True)

    # --- recording -----------------------------------------------------------------------------

    @staticmethod
    def _input_record(started: datetime, check: InputCheck) -> _StepRecord:
        detail = _verdict_detail(check.verdict, guard_down=check.guard_down)
        return _StepRecord(
            StepName.SAFETY_IN, started, check.verdict, check.usage, detail, check.verdict.decision
        )

    @staticmethod
    def _output_record(started: datetime, check: OutputCheck) -> _StepRecord:
        detail = _verdict_detail(check.verdict, guard_down=check.guard_down)
        if check.overruled:
            cleared = ",".join(category.value for category in check.overruled)
            detail = f"{detail} guard_flagged={cleared}"
        return _StepRecord(
            StepName.SAFETY_OUT, started, check.verdict, check.usage, detail, check.verdict.decision
        )

    async def _record(self, record: _StepRecord) -> None:
        duration_ms = self._elapsed_ms(record.started)
        await self._safely(
            self.recorder.record(
                turn_id=self.ctx.turn_id,
                step=record.step,
                outcome=record.outcome,
                started_at=record.started,
                duration_ms=duration_ms,
                usage=record.usage,
                failure=None,
                detail=record.detail,
                decision=record.decision,
            )
        )
        result = StepSuccess[object](step=record.step, output=record.output, outcome=record.outcome)
        await self.observer.on_step(
            self.ctx.turn_id, record.step, result, record.usage, duration_ms
        )

    async def _record_skipped(self, step: StepName, detail: str) -> None:
        await self._safely(
            self.recorder.record(
                turn_id=self.ctx.turn_id,
                step=step,
                outcome=StepOutcome.SKIPPED,
                started_at=self.steps.clock.now(),
                duration_ms=0,
                usage=None,
                failure=None,
                detail=detail,
            )
        )

    async def _safely(self, recording: Awaitable[None]) -> None:
        """Step rows are telemetry: a failed write is logged and the turn goes on (s05 §4.5)."""
        try:
            await recording
        except StoreError as exc:
            logger.exception("step_record_failed", turn_id=str(self.ctx.turn_id), exc_info=exc)

    def _elapsed_ms(self, started: datetime) -> int:
        return max(int((self.steps.clock.now() - started).total_seconds() * 1000), 0)


def _verdict_detail(verdict: SafetyVerdict, *, guard_down: bool) -> str:
    """Fixed vocabulary for turn_steps.detail: the decision, the codes, and whether the backup
    decided because Llama Guard was down. Never the text."""
    detail = f"decision={verdict.decision.value}"
    if verdict.categories:
        flagged = ",".join(category.value for category in verdict.categories)
        detail = f"{detail} categories={flagged}"
    if guard_down:
        detail = f"{detail} guard=down"
    return detail
