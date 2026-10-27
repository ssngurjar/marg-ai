"""Orchestrator: one turn from the user's messages to a sealed reply (s05 §4.5, mvp-scope §4.2).

    A. user text            text and transcribed voice notes, in the order sent (S6: fetch,
                            convert, check for silence and length, transcribe); images aren't
                            understood before S10b
    B. route ‖ safety_in ‖ generate
                            generation starts with the safety check, and its result is used ONLY
                            if safety_in returns ALLOW; otherwise it's cancelled, unread (C3a)
    C. translate            SKIPPED: the layer wrote in the user's register (C3c)
    D. safety_out           the generated reply is sealed only if Llama Guard allows it
    E. parts                ReplyPartsBuilder → TurnOutcome
    F. synthesize           when the user spoke: the sealed reply's spoken text (checked by
                            safety_out with the text) as a voice note; on failure, text only

Child talk (s10b §4.16, C13) runs the same way with the child as the speaker: the reply is always
spoken, safety_out adds the child rules, and a crisis gets the child-worded helpline text and
ends the session (after an abuse disclosure the parent is told nothing, C15).

Onboarding and deletion turns (s08) run safety_in, then the onboarding layer, whose reply is
reviewed fixed copy (sealed without a classifier call) and whose writes ride on the outcome.

Every turn ends with a reply. A provider failure becomes a fixed reply (HOLDING when a safety
check fails: fail closed); only a programming error raises, which the worker treats as a crashed
turn. Every step is recorded; a recording failure is logged and never takes the reply down.
"""

import asyncio
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar, Final, Literal

from app.constants.child_talk_copy import PARENT_SUMMARY_AFTER_SADNESS, UNNAMED_CHILD_NAME
from app.constants.journey_copy import NUDGE_ASK, NUDGE_BUTTONS
from app.constants.stt_keywords import STT_KEYWORDS
from app.core.clock import Clock
from app.core.errors import (
    DomainError,
    MediaError,
    MediaUnsupported,
    ProviderError,
    SafetyUnavailable,
    StoreError,
)
from app.core.logging import get_logger
from app.domain.enums import (
    AudioVerdict,
    ChildSessionEndReason,
    FailureKind,
    FixedReplyKind,
    FixedReplyVariant,
    Language,
    MessageKind,
    Route,
    SafetyDecision,
    Speaker,
    StepName,
    StepOutcome,
)
from app.domain.models.curiosity import ExtractSignals, PostTurnTask
from app.domain.models.message import InboundMessage
from app.domain.models.reply import CanonicalReply, LocalisedReply
from app.domain.models.safety import SafetyVerdict
from app.domain.models.turn import TurnContext
from app.domain.models.usage import StepUsage
from app.domain.models.voice import VoiceLimits
from app.domain.models.writes import ChildSessionEnd, TurnWrite
from app.domain.rules.audio_analyser import AudioAnalyser
from app.domain.rules.filler_detector import FillerDetector
from app.domain.rules.register_detector import RegisterDetector
from app.domain.rules.stage_rules import StageRules
from app.layers.child_talk_layer import ChildTalkLayer
from app.layers.journey_layer import JourneyLayer
from app.layers.layer_result import LayerResult
from app.layers.onboarding_layer import FirstKhojHandoff, OnboardingLayer, OnboardingResult
from app.pipeline.failure_policy import FailurePolicy
from app.pipeline.fixed_reply_service import FixedReplyService
from app.pipeline.reply_parts_builder import ReplyDelivery, ReplyPartsBuilder
from app.pipeline.step_models import StepFailure, StepSuccess, TurnOutcome
from app.pipeline.turn_protocols import StepRecorder, TurnObserver
from app.pipeline.turn_router import TurnRouter
from app.providers.ports import (
    AudioConverter,
    MediaFetcher,
    ReplyAudioStore,
    Synthesizer,
    Transcriber,
    TranscriptionHints,
)
from app.safety.safety_gate import InputCheck, OutputCheck, SafeReply, SafetyGate

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
    fetch_media_timeout: timedelta  # TIMEOUT_FETCH_MEDIA_S: the download and the conversion
    transcribe_timeout: timedelta
    synthesize_timeout: timedelta


@dataclass(frozen=True, slots=True)
class VoiceSteps:
    """What voice notes in and voice replies out need (s06)."""

    fetcher: MediaFetcher
    converter: AudioConverter
    transcriber: Transcriber
    synthesizer: Synthesizer
    audio_store: ReplyAudioStore
    limits: VoiceLimits
    reply_audio_for_text_input: bool  # REPLY_AUDIO_FOR_TEXT_INPUT (C9)


@dataclass(frozen=True, slots=True)
class PipelineSteps:
    gate: SafetyGate
    journey: JourneyLayer
    onboarding: OnboardingLayer
    voice: VoiceSteps
    child_talk: ChildTalkLayer | None  # None when CHILD_TALK_ENABLED is false
    clock: Clock


@dataclass(frozen=True, slots=True)
class _FixedChoice:
    kind: FixedReplyKind
    variant: FixedReplyVariant
    route: Route


@dataclass(frozen=True, slots=True)
class _Sent:
    """A reply that passed safety_out, and the writes that go with it."""

    safe: SafeReply
    writes: tuple[TurnWrite, ...]


@dataclass(frozen=True, slots=True)
class _Sealed:
    """The reply the turn's delivery was built from, kept so its audio can be added."""

    safe: SafeReply
    preamble: SafeReply | None
    trailer: SafeReply | None = None


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
        self.register = self.ctx.profile.language or FALLBACK_REGISTER
        self.voice_turn = False  # the user sent at least one voice note (or a child is talking)
        self.speaker = Speaker.GUIDE
        self.sealed: _Sealed | None = None

    async def run(self) -> TurnOutcome:
        outcome = await self._answer()
        return await self._with_voice(outcome)

    async def _answer(self) -> TurnOutcome:
        read = await self._read_messages()
        if isinstance(read, TurnOutcome):
            return read
        interactive_ids, has_unsupported = read
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
        decision = TurnRouter.decide(
            self.ctx.profile,
            self.user_text,
            interactive_ids,
            learners=self.ctx.learners,
            child_session_open=self.ctx.child_session is not None,
        )
        if decision.route is Route.CHILD_TALK and self.steps.child_talk is None:
            # Switched off: "Main Munni hoon" is just a message; a kid: button means nothing.
            route = Route.REPEAT_PLEASE if interactive_ids else Route.JOURNEY
            decision = decision.model_copy(
                update={"route": route, "reason": "child talk switched off"}
            )
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
        if decision.route is Route.CHILD_TALK and self.steps.child_talk is not None:
            return await self._child_talk(self.steps.child_talk, interactive_ids)
        return await self._journey(interactive_ids)

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
        return await self._onboarding_outcome(route, result)

    async def _onboarding_outcome(self, route: Route, result: OnboardingResult) -> TurnOutcome:
        """Onboarding copy is reviewed fixed text: sealed without a classifier call (s07 §4.2).
        A parent's first child gets the first khoj in the same turn (s08 §4.7); if that fails,
        onboarding still completes and the parent can ask for it."""
        reply = result.reply
        kind = reply.fixed_kind or FixedReplyKind.ONBOARDING
        safe = self.steps.gate.clear_fixed(_localised(reply), kind)
        writes: list[TurnWrite] = list(result.writes)
        delivery = self._delivery(safe)
        if isinstance(result.handoff, FirstKhojHandoff):
            khoj = await self._first_khoj(result.handoff, safe.reply_register)
            if khoj is not None:
                delivery = self._delivery(khoj.safe, preamble=safe, trailer=self._nudge_ask())
                writes.extend(khoj.writes)
        return TurnOutcome(
            turn_id=self.ctx.turn_id,
            route=route,
            delivery=delivery,
            fixed_reply_kind=kind,
            user_text=self.user_text or None,
            reply_text=safe.text,
            reply_register=safe.reply_register,
            prompt_versions=self.prompt_versions,
            first_failure=self.first_failure,
            writes=writes,
        )

    async def _first_khoj(self, handoff: FirstKhojHandoff, register: Language) -> "_Sent | None":
        learner = handoff.learner
        ctx = self.ctx.model_copy(
            update={
                "learners": [*self.ctx.learners, learner],
                "active_learner": learner,
                "open_activity": None,
                "activity_history": [],
            }
        )
        started = self.steps.clock.now()
        try:
            layer_result = await self._bounded(
                self.steps.journey.first_khoj(ctx, learner, self.steps.clock.now(), register),
                self.settings.generate_timeout,
            )
        except (ProviderError, DomainError, TimeoutError) as error:
            await self._record_failure(StepName.GENERATE, started, error, "first_khoj")
            return None
        self.prompt_versions.update(layer_result.prompt_versions)
        await self._record(
            _StepRecord(
                StepName.GENERATE,
                started,
                layer_result,
                StepUsage.total(layer_result.usages),
                layer_result.degraded_reason or "first_khoj",
                outcome=layer_result.outcome,
            )
        )
        checked = await self._checked(layer_result)
        if not isinstance(checked, _Sent):
            return None
        return checked

    async def _journey(self, interactive_ids: list[str]) -> TurnOutcome:
        started = self.steps.clock.now()
        generation = asyncio.create_task(self._generate(interactive_ids))
        if self.user_text:  # a button press carries our own id, nothing typed to check
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

    async def _child_talk(self, layer: ChildTalkLayer, interactive_ids: list[str]) -> TurnOutcome:
        """A child talking (C13): like the journey, with the child as the speaker."""
        self.speaker = Speaker.LEARNER
        self.voice_turn = True  # voice-first for children: every reply is spoken
        # A child's few words ("bye", "Main Munni hoon") are poor evidence of a language: the
        # family's onboarding language decides when there is one.
        self.register = self.ctx.profile.language or self.register
        started = self.steps.clock.now()
        generation = asyncio.create_task(self._child_generate(layer, interactive_ids))
        if self.user_text:
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
                return self._child_refusal(input_check)
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
        return await self._check_and_seal(layer_result, Route.CHILD_TALK)

    async def _child_generate(
        self, layer: ChildTalkLayer, interactive_ids: list[str]
    ) -> LayerResult:
        return await self._bounded(
            layer.handle(
                self.ctx,
                self.user_text,
                interactive_ids,
                self.steps.clock.now(),
                self.register,
            ),
            self.settings.generate_timeout,
        )

    def _child_refusal(self, check: InputCheck) -> TurnOutcome:
        """Child-worded fixed text. A crisis ends the session; after sadness or self-harm the
        parent gets a gentle note with the adult helpline, after an abuse disclosure nothing
        (C15): the adult reading the phone may be the one causing harm."""
        choice = self._refusal_for(check)
        session = self.ctx.child_session
        if choice.kind is not FixedReplyKind.CRISIS or session is None:
            return self._fixed(choice)
        end = ChildSessionEnd(session_id=session.id, reason=ChildSessionEndReason.CRISIS)
        if choice.variant is not FixedReplyVariant.SELF_HARM:
            return self._fixed(choice, writes=(end,))
        learner = self.ctx.active_learner
        name = (learner.nickname if learner else None) or UNNAMED_CHILD_NAME[self.register]
        note = PARENT_SUMMARY_AFTER_SADNESS[self.register].format(name=name)
        return self._fixed(choice, writes=(end,), parent_note=note)

    async def _generate(self, interactive_ids: list[str]) -> LayerResult:
        """The layer call is made inside the task, so a task cancelled before it starts leaves
        no un-awaited coroutine behind."""
        return await self._bounded(
            self.steps.journey.handle(
                self.ctx,
                self.user_text,
                interactive_ids,
                self.steps.clock.now(),
                self.register,
            ),
            self.settings.generate_timeout,
        )

    async def _check_and_seal(
        self, layer_result: LayerResult, route: Route = Route.JOURNEY
    ) -> TurnOutcome:
        checked = await self._checked(layer_result)
        if isinstance(checked, TurnOutcome):
            return checked
        if checked is None:
            # Our own reply was flagged: a fixed redirect, nothing generated goes out, and
            # nothing the reply would have recorded is written.
            return self._fixed(
                _FixedChoice(FixedReplyKind.REFUSE, FixedReplyVariant.GENERIC, route)
            )
        return TurnOutcome(
            turn_id=self.ctx.turn_id,
            route=route,
            delivery=self._delivery(checked.safe),
            fixed_reply_kind=None,
            user_text=self.user_text or None,
            reply_text=checked.safe.text,
            reply_register=checked.safe.reply_register,
            prompt_versions=self.prompt_versions,
            first_failure=self.first_failure,
            writes=list(checked.writes),
            post_turn=self._signals_for(layer_result),
        )

    def _signals_for(self, layer_result: LayerResult) -> list[PostTurnTask]:
        """Curiosity extraction after the reply (s13 §4.2): only for a generated reply that was
        sent, about a known child, with words to judge."""
        source = layer_result.curiosity
        if source is None or not self.user_text.strip():
            return []
        learner = next(
            (known for known in self.ctx.learners if known.id == source.learner_id), None
        )
        age = (
            StageRules.age_on(learner.birth_year, self.steps.clock.now().date())
            if learner
            else None
        )
        return [
            ExtractSignals(
                turn_id=self.ctx.turn_id,
                learner_id=source.learner_id,
                user_text=self.user_text,
                source=source,
                child_age=age,
            )
        ]

    async def _checked(self, layer_result: LayerResult) -> "_Sent | TurnOutcome | None":
        """safety_out on the layer's reply; if it's blocked and the layer has reviewed text to
        fall back on (s10b §4.10), that is checked instead. A safety failure is the HOLDING
        outcome; None means nothing may be sent."""
        for reply in (layer_result.reply, layer_result.fallback_reply):
            if reply is None:
                continue
            started = self.steps.clock.now()
            try:
                output_check = await self._bounded(
                    self.steps.gate.check_output(
                        _localised(reply),
                        self.user_text,
                        hazard_rule=layer_result.hazard_rule,
                        speaker=self.speaker,
                    ),
                    self.settings.safety_out_timeout,
                )
            except (SafetyUnavailable, TimeoutError) as error:
                return await self._failed(StepName.SAFETY_OUT, started, error)
            await self._record(self._output_record(started, output_check))
            if output_check.safe_reply is not None:
                return _Sent(output_check.safe_reply, tuple(layer_result.writes))
        return None

    # --- turn pieces -------------------------------------------------------------------------

    async def _read_messages(self) -> "tuple[list[str], bool] | TurnOutcome":
        """Sets the combined user text: typed text and transcribed voice notes, in the order
        sent. Returns the interactive ids and whether an unsupported message came, or the fixed
        reply when a voice note couldn't be heard."""
        pieces: list[str] = []
        interactive_ids: list[str] = []
        has_unsupported = False
        for message in self.ctx.messages:
            if message.kind is MessageKind.TEXT and message.text and message.text.strip():
                pieces.append(message.text.strip())
            elif message.kind is MessageKind.INTERACTIVE and message.interactive_reply_id:
                interactive_ids.append(message.interactive_reply_id)
            elif message.kind is MessageKind.AUDIO:
                self.voice_turn = True
                heard = await self._hear(message)
                if isinstance(heard, TurnOutcome):
                    return heard
                pieces.append(heard)
            elif message.kind is not MessageKind.TEXT:  # IMAGE before S10b's photos
                has_unsupported = True
        self.user_text = "\n".join(pieces)
        return interactive_ids, has_unsupported

    # --- voice (s06) ----------------------------------------------------------------------------

    async def _hear(self, message: InboundMessage) -> "str | TurnOutcome":
        """A voice note's words, or the fixed reply for why it couldn't be heard (s06 §8)."""
        voice = self.steps.voice
        started = self.steps.clock.now()
        if message.media is None:
            return await self._not_heard(
                StepName.FETCH_MEDIA, started, MediaUnsupported("audio message without media")
            )
        try:
            clip = await self._bounded(
                voice.fetcher.fetch(message.media), self.settings.fetch_media_timeout
            )
            wav = await self._bounded(
                voice.converter.to_stt_wav(clip), self.settings.fetch_media_timeout
            )
        except (ProviderError, MediaError, TimeoutError) as error:
            return await self._not_heard(StepName.FETCH_MEDIA, started, error)
        stats = AudioAnalyser.analyse_wav(wav.data)
        measured = f"duration_ms={stats.duration_ms} voiced_ms={stats.voiced_ms}"
        await self._record(_StepRecord(StepName.FETCH_MEDIA, started, None, None, measured))
        started = self.steps.clock.now()
        verdict = AudioAnalyser.verdict(stats, voice.limits)
        if verdict is not AudioVerdict.OK:
            return await self._refused_voice_note(started, verdict)
        try:
            transcript, usage = await self._bounded(
                voice.transcriber.transcribe(wav, self._hints()),
                self.settings.transcribe_timeout,
            )
        except (ProviderError, TimeoutError) as error:
            return await self._not_heard(StepName.TRANSCRIBE, started, error)
        if FillerDetector.is_only_filler(transcript.text):
            nothing = StepFailure(
                step=StepName.TRANSCRIBE,
                kind=FailureKind.EMPTY_INPUT,
                detail="nothing_said",
                retryable=False,
            )
            await self._record_failed_step(started, nothing, "fallback=repeat_please", usage)
            return self._fixed(self._voice_reply(FixedReplyKind.REPEAT_PLEASE))
        language = transcript.language.value if transcript.language else "unknown"
        await self._record(
            _StepRecord(StepName.TRANSCRIBE, started, transcript, usage, f"language={language}")
        )
        return transcript.text

    def _hints(self) -> TranscriptionHints:
        expected = [self.ctx.profile.language or FALLBACK_REGISTER]
        return TranscriptionHints(expected_languages=expected, keywords=list(STT_KEYWORDS))

    async def _not_heard(
        self, step: StepName, started: datetime, error: BaseException
    ) -> TurnOutcome:
        kind = FailurePolicy.reply_for_voice_note(error)
        await self._record_failure(step, started, error, f"fallback={kind.value}")
        return self._fixed(self._voice_reply(kind))

    async def _refused_voice_note(self, started: datetime, verdict: AudioVerdict) -> TurnOutcome:
        """Too short, silent or too long: answered without a speech-to-text call."""
        too_long = verdict is AudioVerdict.TOO_LONG
        kind = FixedReplyKind.TOO_LONG if too_long else FixedReplyKind.REPEAT_PLEASE
        failure = StepFailure(
            step=StepName.TRANSCRIBE,
            kind=FailureKind.UNSUPPORTED_INPUT if too_long else FailureKind.EMPTY_INPUT,
            detail=verdict.value,
            retryable=False,
        )
        await self._record_failed_step(started, failure, f"fallback={kind.value}", None)
        return self._fixed(self._voice_reply(kind))

    @staticmethod
    def _voice_reply(kind: FixedReplyKind) -> _FixedChoice:
        return _FixedChoice(kind, FixedReplyVariant.DEFAULT, Route.REPEAT_PLEASE)

    async def _with_voice(self, outcome: TurnOutcome) -> TurnOutcome:
        """The sealed reply as a voice note too, when the user spoke (or REPLY_AUDIO_FOR_TEXT_
        INPUT). Its spoken text passed safety_out with the text. Any failure leaves the reply
        as text only (DEGRADED, s06 §8)."""
        voice = self.steps.voice
        if self.sealed is None or not (self.voice_turn or voice.reply_audio_for_text_input):
            return outcome
        safe = self.sealed.safe
        started = self.steps.clock.now()
        try:
            clip, usage = await self._bounded(
                voice.synthesizer.synthesize(safe.spoken_text, safe.reply_register),
                self.settings.synthesize_timeout,
            )
            blob_id = await voice.audio_store.save(self.ctx.profile.user_hash, clip)
        except (ProviderError, MediaError, StoreError, TimeoutError) as error:
            await self._record_failure(StepName.SYNTHESIZE, started, error, "text_only")
            return outcome.model_copy(update={"first_failure": self.first_failure})
        await self._record(
            _StepRecord(StepName.SYNTHESIZE, started, None, usage, f"voice={safe.reply_register}")
        )
        delivery = ReplyPartsBuilder.build(
            safe, audio_blob_id=blob_id, preamble=self.sealed.preamble, trailer=self.sealed.trailer
        )
        return outcome.model_copy(update={"delivery": delivery})

    def _delivery(
        self,
        safe: SafeReply,
        preamble: SafeReply | None = None,
        trailer: SafeReply | None = None,
    ) -> ReplyDelivery:
        """Text parts for `safe`; the reply is remembered so its voice note can be added."""
        self.sealed = _Sealed(safe, preamble, trailer)
        return ReplyPartsBuilder.build(safe, audio_blob_id=None, preamble=preamble, trailer=trailer)

    def _nudge_ask(self) -> SafeReply:
        """After the first khoj: when should the daily one come? (s10b §4.11; fixed copy)."""
        ask = LocalisedReply(
            text=NUDGE_ASK[self.register],
            spoken_text=NUDGE_ASK[self.register],
            reply_register=self.register,
            citations=[],
            buttons=list(NUDGE_BUTTONS[self.register]),
        )
        return self.steps.gate.clear_fixed(ask, FixedReplyKind.ONBOARDING)

    @staticmethod
    def _refusal_for(check: InputCheck) -> _FixedChoice:
        variant = check.variant or FixedReplyVariant.GENERAL
        if check.verdict.decision is SafetyDecision.CRISIS:
            return _FixedChoice(FixedReplyKind.CRISIS, variant, Route.CRISIS)
        return _FixedChoice(FixedReplyKind.REFUSE, variant, Route.REFUSE)

    async def _failed(self, step: StepName, started: datetime, error: BaseException) -> TurnOutcome:
        """Record the failure and answer with the step's fallback (s05 §4.5 table)."""
        fallback = FailurePolicy.reply_for(step)
        await self._record_failure(step, started, error, f"fallback={fallback.value}")
        return self._fixed(_FixedChoice(fallback, FixedReplyVariant.DEFAULT, Route.JOURNEY))

    async def _record_failure(
        self, step: StepName, started: datetime, error: BaseException, detail: str
    ) -> None:
        failure = StepFailure(
            step=step,
            kind=FailurePolicy.kind_of(error),
            detail=type(error).__name__,  # never the message: it can quote generated text
            retryable=FailurePolicy.is_retryable(error),
        )
        await self._record_failed_step(started, failure, detail, None)

    async def _record_failed_step(
        self, started: datetime, failure: StepFailure, detail: str, usage: StepUsage | None
    ) -> None:
        """`usage`: a call that was made and billed before the step failed (an empty
        transcript is still paid for)."""
        if self.first_failure is None:
            self.first_failure = failure
        duration_ms = self._elapsed_ms(started)
        await self._safely(
            self.recorder.record(
                turn_id=self.ctx.turn_id,
                step=failure.step,
                outcome=StepOutcome.FAILED,
                started_at=started,
                duration_ms=duration_ms,
                usage=usage,
                failure=failure,
                detail=detail,
            )
        )
        await self.observer.on_step(self.ctx.turn_id, failure.step, failure, usage, duration_ms)

    def _fixed(
        self,
        choice: _FixedChoice,
        writes: Sequence[TurnWrite] = (),
        parent_note: str | None = None,
    ) -> TurnOutcome:
        """A reviewed fixed text, sealed without a classifier call (s07 §4.2). `parent_note`
        (fixed copy too) follows it in writing only, never spoken."""
        localised = FixedReplyService.localise(
            choice.kind, choice.variant, self.register, self.speaker
        )
        if parent_note is not None:
            localised = localised.model_copy(update={"text": f"{localised.text}\n\n{parent_note}"})
        safe = self.steps.gate.clear_fixed(localised, choice.kind)
        return TurnOutcome(
            turn_id=self.ctx.turn_id,
            route=choice.route,
            delivery=self._delivery(safe),
            fixed_reply_kind=choice.kind,
            user_text=self.user_text or None,
            reply_text=safe.text,
            reply_register=safe.reply_register,
            prompt_versions=self.prompt_versions,
            first_failure=self.first_failure,
            writes=list(writes),
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


def _localised(reply: CanonicalReply) -> LocalisedReply:
    return LocalisedReply(
        text=reply.body,
        spoken_text=reply.spoken_text or reply.body,
        reply_register=reply.body_language,
        citations=reply.citations,
        buttons=reply.buttons,
    )
