"""Composition root: the only module that builds concrete adapters.

Everything else receives its dependencies. Each step adds what it builds to `Container`. Startup
checks run here, so a bad configuration fails the deploy, not a user's turn: no Contributor-mode
model on user content, every fixed reply in every language, every prompt template valid.
"""

import os
import random
import socket
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import Final
from urllib.parse import quote
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.readiness import ReadinessProbe
from app.audio.audio_transcoder import AudioTranscoder
from app.audio.ffmpeg_runner import FfmpegRunner
from app.channels.whatsapp.whatsapp_media_fetcher import MediaFetchConfig, WhatsAppMediaFetcher
from app.channels.whatsapp.whatsapp_sender import WhatsAppConfig, WhatsAppSender
from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.core.user_identity import UserIdentity
from app.domain.enums import Channel
from app.domain.models.voice import VoiceLimits
from app.domain.rules.child_session_rules import ChildSessionLimits
from app.layers.activity_catalogue import ActivityCatalogue, CatalogueActivitySource
from app.layers.child_talk_layer import CHILD_TALK, ChildTalkLayer
from app.layers.curiosity_moment_layer import CURIOSITY_MOMENT
from app.layers.journey_layer import (
    ACTIVITY_PERSONALISE,
    PARENT_REFLECTION,
    JourneyLayer,
    JourneySettings,
)
from app.layers.khoj_card_maker import KHOJ_CARD_TEXT, KhojCardMaker
from app.layers.onboarding_layer import PROFILE_EXTRACTION, OnboardingLayer
from app.layers.parent_question_layer import PARENT_ANSWER, ParentQuestionLayer
from app.pipeline.fixed_reply_service import FixedReplyService
from app.pipeline.orchestrator import (
    Orchestrator,
    OrchestratorSettings,
    PipelineSteps,
    VoiceSteps,
)
from app.prompts.prompt_registry import PromptRegistry, PromptSettings
from app.providers.http import AsyncioSleeper, RetryPolicy, RetryTiming
from app.providers.image.image_compressor import ImageCompressor
from app.providers.image.muse_image_generator import ImageModelConfig, MuseImageGenerator
from app.providers.llm.fallback_language_model import FallbackLanguageModel, FallbackRoute
from app.providers.llm.meta_model_api_language_model import (
    MetaModelApiLanguageModel,
    ModelApiConfig,
)
from app.providers.llm.model_pricing import ModelPricing
from app.providers.ports import ChannelSender, LanguageModel, SafetyClassifier
from app.providers.safety.llama_guard_classifier import LlamaGuardClassifier, SafetyHostConfig
from app.providers.speech.muse_voice_transcriber import MuseVoiceTranscriber, TranscriberConfig
from app.providers.speech.sidecar_synthesizer import SidecarConfig, SidecarSynthesizer
from app.safety.domain_policy import MINOR_POLICY, REPLY_POLICY, DomainPolicy, PolicyModel
from app.safety.safety_gate import SafetyGate
from app.store.db import create_engine, create_session_factory, ping
from app.store.repositories.child_session_repository import ChildSessionRepository
from app.store.repositories.curiosity_signal_repository import CuriositySignalRepository
from app.store.repositories.inbox_repository import InboxRepository
from app.store.repositories.khoj_card_repository import KhojCardRepository
from app.store.repositories.media_blob_repository import MediaBlobRepository
from app.store.repositories.nudge_repository import NudgeRepository
from app.store.repositories.outbox_repository import OutboxRepository
from app.store.repositories.turn_repository import TurnRepository
from app.store.repositories.turn_step_repository import TurnStepRepository
from app.store.repositories.user_repository import UserRepository
from app.telemetry.curiosity_signal_extractor import CURIOSITY_EXTRACT, CuriositySignalExtractor
from app.worker.database_step_recorder import DatabaseStepRecorder
from app.worker.khoj_card_sender import CardDeps, KhojCardSender
from app.worker.nudge_sender import NudgeSender, NudgeSettings, nudge_templates
from app.worker.post_turn_runner import PostTurnDeps, PostTurnRunner
from app.worker.reply_deliverer import DeliveryDeps, DeliverySettings, ReplyDeliverer
from app.worker.turn_dispatcher import DispatcherDeps, DispatcherSettings, TurnDispatcher
from app.worker.turn_processor import TurnDeps, TurnProcessor, TurnSettings

DISPATCHER_ERROR_BACKOFF = timedelta(seconds=5)
PROMPT_SPECS: Final = (
    PARENT_ANSWER,
    MINOR_POLICY,
    REPLY_POLICY,
    PROFILE_EXTRACTION,
    ACTIVITY_PERSONALISE,
    PARENT_REFLECTION,
    CURIOSITY_MOMENT,
    CHILD_TALK,
    CURIOSITY_EXTRACT,
    KHOJ_CARD_TEXT,
)
"""Every prompt the app renders; the registry refuses a template without a spec."""
INVITE_GREETING: Final = "Namaste Marg"


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    clock: Clock
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    readiness_probes: tuple[ReadinessProbe, ...]
    identity: UserIdentity
    whatsapp_sender: WhatsAppSender
    inbox_repository: InboxRepository
    outbox_repository: OutboxRepository
    language_models: tuple[MetaModelApiLanguageModel, ...]  # Spark and Muse Spark Open
    safety_classifier: LlamaGuardClassifier
    voice_adapters: "VoiceAdapters"
    image_generator: MuseImageGenerator
    turn_dispatcher: TurnDispatcher


@dataclass(frozen=True, slots=True)
class OrchestratorPorts:
    language_model: LanguageModel
    safety_classifier: SafetyClassifier
    voice: VoiceSteps


@dataclass(frozen=True, slots=True)
class VoiceAdapters:
    """The concrete voice adapters, kept so they can be closed on shutdown."""

    fetcher: WhatsAppMediaFetcher
    transcoder: AudioTranscoder
    transcriber: MuseVoiceTranscriber
    synthesizer: SidecarSynthesizer
    media: MediaBlobRepository


def build_container(settings: Settings) -> Container:
    check_startup(settings)
    catalogue = ActivityCatalogue.load()  # refuses to start on an invalid activity
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    clock = SystemClock()
    identity = UserIdentity(settings.user_hash_salt, settings.address_encryption_key)
    retry = RetryPolicy(
        timing=RetryTiming(), clock=clock, sleeper=AsyncioSleeper(), rng=random.SystemRandom()
    )
    whatsapp_sender = WhatsAppSender(
        config=WhatsAppConfig(
            graph_base_url=str(settings.whatsapp_graph_base_url),
            phone_number_id=settings.whatsapp_phone_number_id,
            access_token=settings.whatsapp_access_token,
            timeout_s=settings.timeout_whatsapp_s,
        ),
        clock=clock,
    )
    spark = MetaModelApiLanguageModel(
        config=ModelApiConfig(
            base_url=str(settings.model_api_base_url),
            api_key=settings.model_api_key,
            timeout_s=settings.timeout_generate_s,
        ),
        retry=retry,
        clock=clock,
    )
    open_model = MetaModelApiLanguageModel(
        config=ModelApiConfig(
            base_url=str(settings.open_model_base_url),
            api_key=settings.open_model_api_key,
            timeout_s=settings.timeout_open_model_s,
        ),
        retry=retry,
        clock=clock,
    )
    language_model = FallbackLanguageModel(
        open_model,
        spark,
        FallbackRoute(
            primary_model=settings.open_model,
            fallback_model=settings.model_text,
            primary_timeout=timedelta(seconds=settings.timeout_open_model_s),
        ),
    )
    safety_classifier = LlamaGuardClassifier(
        config=SafetyHostConfig(
            base_url=str(settings.safety_base_url),
            api_key=settings.safety_api_key,
            model=settings.safety_model,
            timeout_s=settings.timeout_guard_s,
        ),
        retry=retry,
        clock=clock,
    )
    voice_adapters = build_voice_adapters(settings, session_factory, retry, clock)
    image_generator = MuseImageGenerator(
        config=ImageModelConfig(
            base_url=str(settings.model_api_base_url),
            api_key=settings.model_api_key,
            model=settings.model_image,
            reasoning_strength=settings.image_reasoning_strength,
            timeout_s=settings.timeout_make_card_s,
        ),
        retry=retry,
        clock=clock,
        compressor=ImageCompressor(FfmpegRunner(timeout_s=settings.transcode_timeout_s)),
    )
    inbox = InboxRepository(session_factory)
    outbox = OutboxRepository(session_factory)
    dispatcher = build_turn_dispatcher(
        settings=settings,
        session_factory=session_factory,
        engine_parts=EngineParts(
            clock=clock,
            identity=identity,
            retry=retry,
            senders={Channel.WHATSAPP: whatsapp_sender},
            orchestrator=build_orchestrator(
                settings,
                OrchestratorPorts(
                    language_model, safety_classifier, voice_steps(settings, voice_adapters)
                ),
                clock,
                catalogue=catalogue,
            ),
            outbox=outbox,
            media=voice_adapters.media,
            signals=CuriositySignalExtractor(language_model, prompt_registry(settings)),
            cards=(
                KhojCardMaker(spark, image_generator, prompt_registry(settings))
                if settings.khoj_card_enabled
                else None
            ),
        ),
    )
    return Container(
        settings=settings,
        clock=clock,
        engine=engine,
        session_factory=session_factory,
        readiness_probes=(
            ReadinessProbe(name="database", critical=True, check=partial(ping, engine)),
            # Voice degrades to text when these fail, so they don't take the app out of service
            ReadinessProbe(
                name="ffmpeg", critical=False, check=voice_adapters.transcoder.check_encoders
            ),
        ),
        identity=identity,
        whatsapp_sender=whatsapp_sender,
        inbox_repository=inbox,
        outbox_repository=outbox,
        language_models=(spark, open_model),
        safety_classifier=safety_classifier,
        voice_adapters=voice_adapters,
        image_generator=image_generator,
        turn_dispatcher=dispatcher,
    )


def build_voice_adapters(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    retry: RetryPolicy,
    clock: Clock,
) -> VoiceAdapters:
    """Voice notes in (WhatsApp download, ffmpeg, Muse Voice Transcribe) and out (the voice
    server running TTS_ENGINE, ffmpeg). s06."""
    transcoder = AudioTranscoder(timeout_s=settings.transcode_timeout_s)
    return VoiceAdapters(
        fetcher=WhatsAppMediaFetcher(
            config=MediaFetchConfig(
                graph_base_url=str(settings.whatsapp_graph_base_url),
                access_token=settings.whatsapp_access_token,
                timeout_s=settings.timeout_fetch_media_s,
                max_bytes=settings.max_inbound_audio_bytes,
            ),
            retry=retry,
            clock=clock,
        ),
        transcoder=transcoder,
        transcriber=MuseVoiceTranscriber(
            config=TranscriberConfig(
                base_url=str(settings.model_api_base_url),
                api_key=settings.model_api_key,
                model=settings.model_stt,
                timeout_s=settings.timeout_transcribe_s,
            ),
            retry=retry,
            clock=clock,
        ),
        synthesizer=SidecarSynthesizer(
            config=SidecarConfig(
                base_url=str(settings.sidecar_base_url),
                token=settings.sidecar_token,
                engine=settings.tts_engine,
                timeout_s=settings.timeout_synthesize_s,
            ),
            transcoder=transcoder,
            retry=retry,
            clock=clock,
        ),
        media=MediaBlobRepository(session_factory),
    )


def voice_steps(settings: Settings, adapters: VoiceAdapters) -> VoiceSteps:
    return VoiceSteps(
        fetcher=adapters.fetcher,
        converter=adapters.transcoder,
        transcriber=adapters.transcriber,
        synthesizer=adapters.synthesizer,
        audio_store=adapters.media,
        limits=VoiceLimits(
            min_duration_ms=settings.min_voice_note_ms,
            min_voiced_ms=settings.min_voiced_ms,
            max_duration_ms=settings.max_voice_note_seconds * 1000,
        ),
        reply_audio_for_text_input=settings.reply_audio_for_text_input,
    )


def check_startup(settings: Settings) -> None:
    """Fail the deploy, not a turn: raises ConfigError naming what's wrong."""
    ModelPricing.require_allowed_for_user_content(settings.model_text, "MODEL_TEXT")
    ModelPricing.require_allowed_for_user_content(settings.open_model, "OPEN_MODEL")
    ModelPricing.price_of(settings.safety_model)
    FixedReplyService.check_all_languages()
    OnboardingLayer.check_copy()


def build_orchestrator(
    settings: Settings,
    ports: OrchestratorPorts,
    clock: Clock,
    *,
    catalogue: ActivityCatalogue | None = None,
) -> Orchestrator:
    language_model = ports.language_model
    registry = prompt_registry(settings)
    return Orchestrator(
        PipelineSteps(
            gate=SafetyGate(
                ports.safety_classifier,
                DomainPolicy(
                    model=PolicyModel(language_model, registry)
                    if settings.safety_policy_model_enabled
                    else None
                ),
                guard_timeout=timedelta(seconds=settings.timeout_guard_s),
            ),
            journey=JourneyLayer(
                language_model,
                registry,
                CatalogueActivitySource(catalogue or ActivityCatalogue.load()),
                ParentQuestionLayer(language_model, registry),
                JourneySettings(
                    repeat_window=timedelta(days=settings.activity_repeat_days),
                    child_talk_enabled=settings.child_talk_enabled,
                ),
            ),
            onboarding=OnboardingLayer(
                language_model, registry, invite_link=teacher_invite_link(settings)
            ),
            voice=ports.voice,
            child_talk=(
                ChildTalkLayer(language_model, registry, child_session_limits(settings))
                if settings.child_talk_enabled
                else None
            ),
            clock=clock,
        ),
        OrchestratorSettings(
            turn_budget=timedelta(seconds=settings.turn_budget_s),
            safety_in_timeout=timedelta(seconds=settings.timeout_safety_in_s),
            generate_timeout=timedelta(seconds=settings.timeout_generate_s),
            safety_out_timeout=timedelta(seconds=settings.timeout_safety_out_s),
            fetch_media_timeout=timedelta(seconds=settings.timeout_fetch_media_s),
            transcribe_timeout=timedelta(seconds=settings.timeout_transcribe_s),
            synthesize_timeout=timedelta(seconds=settings.timeout_synthesize_s),
        ),
    )


def prompt_registry(settings: Settings) -> PromptRegistry:
    return PromptRegistry(
        specs=PROMPT_SPECS,
        settings=PromptSettings(
            models={"MODEL_TEXT": settings.model_text, "OPEN_MODEL": settings.open_model},
            reasoning_effort=settings.model_reasoning_effort,
            user_slot_max_chars=settings.user_slot_max_chars,
        ),
    )


def child_session_limits(settings: Settings) -> ChildSessionLimits:
    return ChildSessionLimits(
        max_turns=settings.child_session_max_turns,
        max_duration=timedelta(minutes=settings.child_session_max_minutes),
        cooldown=timedelta(minutes=settings.child_session_cooldown_minutes),
    )


def teacher_invite_link(settings: Settings) -> str:
    """The link a teacher forwards to parents: opens a chat with Marg, "Namaste" typed in."""
    return f"https://wa.me/{settings.whatsapp_display_number}?text={quote(INVITE_GREETING)}"


@dataclass(frozen=True, slots=True)
class EngineParts:
    clock: Clock
    identity: UserIdentity
    retry: RetryPolicy
    senders: dict[Channel, ChannelSender]
    orchestrator: Orchestrator
    outbox: OutboxRepository
    media: MediaBlobRepository
    signals: CuriositySignalExtractor
    cards: KhojCardMaker | None  # None while KHOJ_CARD_ENABLED is false


def build_turn_dispatcher(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    engine_parts: EngineParts,
) -> TurnDispatcher:
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
    turns = TurnRepository(session_factory)
    processor = TurnProcessor(
        TurnDeps(
            store=turns,
            recorder=DatabaseStepRecorder(TurnStepRepository(session_factory)),
            run_turn=engine_parts.orchestrator.run_turn,
            gate=engine_parts.orchestrator.steps.gate,
            senders=engine_parts.senders,
            clock=engine_parts.clock,
        ),
        TurnSettings(
            worker_id=worker_id,
            max_messages=settings.max_messages_per_turn,
            max_attempts=settings.max_turn_attempts,
            stale_after=timedelta(hours=settings.stale_message_hours),
            recent_exchanges=settings.recent_exchanges,
        ),
    )
    users = UserRepository(session_factory)
    signals = CuriositySignalRepository(session_factory)
    deliverer = ReplyDeliverer(
        DeliveryDeps(
            outbox=engine_parts.outbox,
            users=users,
            senders=engine_parts.senders,
            identity=engine_parts.identity,
            retry=engine_parts.retry,
            clock=engine_parts.clock,
            audio=engine_parts.media,
            images=engine_parts.media,
        ),
        DeliverySettings(
            max_attempts=settings.outbox_max_attempts,
            part_budget=timedelta(seconds=settings.turn_budget_s),
        ),
    )
    return TurnDispatcher(
        DispatcherDeps(
            processor=processor,
            deliverer=deliverer,
            turns=turns,
            outbox=engine_parts.outbox,
            users=users,
            clock=engine_parts.clock,
            media=engine_parts.media,
            child_sessions=ChildSessionRepository(session_factory),
            post_turn=PostTurnRunner(
                PostTurnDeps(
                    extractor=engine_parts.signals,
                    signals=signals,
                    recorder=DatabaseStepRecorder(TurnStepRepository(session_factory)),
                    clock=engine_parts.clock,
                    timeout=timedelta(seconds=settings.timeout_make_card_s),
                    cards=(
                        KhojCardSender(
                            CardDeps(
                                maker=engine_parts.cards,
                                gate=engine_parts.orchestrator.steps.gate,
                                cards=KhojCardRepository(session_factory),
                                signals=signals,
                                deliverer=deliverer,
                                clock=engine_parts.clock,
                            ),
                            worker_id,
                        )
                        if engine_parts.cards is not None
                        else None
                    ),
                )
            ),
            nudges=(
                NudgeSender(
                    NudgeRepository(session_factory),
                    deliverer,
                    engine_parts.orchestrator.steps.gate,
                    engine_parts.clock,
                    NudgeSettings(
                        templates=nudge_templates(
                            settings.nudge_template_name, settings.nudge_template_name_hinglish
                        ),
                        daily_limit=settings.nudge_daily_limit,
                        worker_id=worker_id,
                    ),
                )
                if settings.nudges_enabled
                else None
            ),
        ),
        DispatcherSettings(
            debounce=timedelta(milliseconds=settings.turn_debounce_ms),
            maintenance_interval=timedelta(seconds=settings.maintenance_interval_s),
            shutdown_grace=timedelta(seconds=settings.shutdown_grace_s),
            retain_turn_text=timedelta(days=settings.retention_turn_text_days),
            retain_raw_payload=timedelta(days=settings.retention_raw_payload_days),
            purge_sweep_after=timedelta(seconds=settings.purge_sweep_after_s),
            child_session_max=timedelta(minutes=settings.child_session_max_minutes),
            error_backoff=DISPATCHER_ERROR_BACKOFF,
        ),
    )


async def close_container(container: Container) -> None:
    """Release what the container opened: HTTP connections and the database pool."""
    await container.whatsapp_sender.aclose()
    for language_model in container.language_models:
        await language_model.aclose()
    await container.safety_classifier.aclose()
    await container.voice_adapters.fetcher.aclose()
    await container.voice_adapters.transcriber.aclose()
    await container.voice_adapters.synthesizer.aclose()
    await container.image_generator.aclose()
    await container.engine.dispose()
