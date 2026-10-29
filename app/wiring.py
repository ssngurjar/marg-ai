"""Composition root: the only module that builds concrete adapters.

Everything else receives its dependencies. Each step adds what it builds to `Container`. Startup
checks run here, so a bad configuration fails the deploy, not a user's turn: no Contributor-mode
model on user content, every fixed reply in every language, every prompt template valid.
"""

import os
import random
import socket
from dataclasses import dataclass, replace
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import Final
from urllib.parse import quote
from uuid import uuid4

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.readiness import PROBE_TIMEOUT_S, CachedCheck, ReadinessProbe
from app.api.telemetry_pages import TelemetryPages
from app.api.turn_event_stream import StreamSettings, TurnEventStream
from app.api.turn_progress_hub import StreamLimits, TurnProgressHub
from app.api.web_demo_ingestor import DemoDeps, DemoLimits, WebDemoIngestor
from app.audio.audio_transcoder import AudioTranscoder
from app.audio.ffmpeg_runner import FfmpegRunner
from app.channels.web.web_sender import WebSender
from app.channels.whatsapp.whatsapp_media_fetcher import MediaFetchConfig, WhatsAppMediaFetcher
from app.channels.whatsapp.whatsapp_sender import WhatsAppConfig, WhatsAppSender
from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.core.errors import ProviderUnavailable, StoreError
from app.core.signed_token_codec import SignedTokenCodec
from app.core.user_identity import UserIdentity
from app.domain.enums import Channel, Language
from app.domain.models.eval_judgement import JudgeScore
from app.domain.models.voice import VoiceLimits
from app.domain.rules.child_session_rules import ChildSessionLimits
from app.layers.activity_catalogue import ActivityCatalogue, CatalogueActivitySource
from app.layers.child_talk_layer import CHILD_REDIRECT, CHILD_TALK, ChildTalkLayer
from app.layers.curiosity_moment_layer import CURIOSITY_MOMENT
from app.layers.curriculum_catalogue import ChapterCatalogue
from app.layers.exposure_layer import EXPOSURE, ExposureLayer
from app.layers.journey_layer import (
    ACTIVITY_PERSONALISE,
    PARENT_REFLECTION,
    JourneyLayer,
    JourneySettings,
)
from app.layers.khoj_card_maker import KHOJ_CARD_TEXT, KhojCardMaker
from app.layers.memory_layer import MEMORY, MemoryLayer
from app.layers.mentor_layer import MENTOR, MentorLayer, MentorSettings
from app.layers.onboarding_layer import PROFILE_EXTRACTION, OnboardingLayer
from app.layers.parent_question_layer import PARENT_ANSWER, ParentQuestionLayer
from app.layers.query_rewriter import QUERY_REWRITE
from app.layers.roadmap_layer import ROADMAP, RoadmapLayer
from app.pipeline.channel_media_fetcher import ChannelMediaFetcher
from app.pipeline.fixed_reply_service import FixedReplyService
from app.pipeline.orchestrator import (
    DashboardLinks,
    Orchestrator,
    OrchestratorSettings,
    PhotoSteps,
    PipelineSteps,
    StudentSteps,
    VoiceSteps,
)
from app.prompts.prompt_registry import PromptRegistry, PromptSettings, PromptSpec
from app.providers.health.http_health_check import HealthEndpoint, HttpHealthCheck
from app.providers.http import AsyncioSleeper, RetryPolicy, RetryTiming
from app.providers.image.image_compressor import ImageCompressor
from app.providers.image.muse_image_generator import ImageModelConfig, MuseImageGenerator
from app.providers.image.sam_image_segmenter import SamImageSegmenter, SegmentModelConfig
from app.providers.llm.fallback_language_model import FallbackLanguageModel, FallbackRoute
from app.providers.llm.meta_model_api_language_model import (
    MetaModelApiLanguageModel,
    ModelApiConfig,
)
from app.providers.llm.model_pricing import ModelPricing
from app.providers.ports import (
    ChannelSender,
    ImageGenerator,
    ImageSegmenter,
    LanguageModel,
    SafetyClassifier,
    SafetyRequest,
    Synthesizer,
)
from app.providers.safety.llama_guard_classifier import LlamaGuardClassifier, SafetyHostConfig
from app.providers.speech.muse_voice_transcriber import MuseVoiceTranscriber, TranscriberConfig
from app.providers.speech.sidecar_synthesizer import SidecarConfig, SidecarSynthesizer
from app.rag.retriever import Retriever, RetrieverSettings
from app.safety.domain_policy import MINOR_POLICY, REPLY_POLICY, DomainPolicy, PolicyModel
from app.safety.safety_gate import SafetyGate
from app.store.db import (
    create_engine,
    create_listener_engine,
    create_session_factory,
    ping,
    schema_version,
)
from app.store.notification_listener import ListenerSettings, NotificationListener
from app.store.repositories.aspiration_signal_repository import AspirationSignalRepository
from app.store.repositories.child_session_repository import ChildSessionRepository
from app.store.repositories.chunk_repository import ChunkRepository
from app.store.repositories.curiosity_signal_repository import CuriositySignalRepository
from app.store.repositories.demo_repository import DemoRepository
from app.store.repositories.inbox_repository import InboxRepository
from app.store.repositories.khoj_card_repository import KhojCardRepository
from app.store.repositories.lease_repository import LeaseRepository, LeaseTimes
from app.store.repositories.media_blob_repository import MediaBlobRepository
from app.store.repositories.nudge_repository import NudgeRepository
from app.store.repositories.outbox_repository import OutboxRepository
from app.store.repositories.profile_memory_repository import ProfileMemoryRepository
from app.store.repositories.telemetry_repository import TelemetryRepository
from app.store.repositories.turn_repository import TurnRepository
from app.store.repositories.turn_step_repository import TurnStepRepository
from app.store.repositories.user_repository import UserRepository
from app.store.turn_progress_notifier import CHANNEL as TURN_PROGRESS
from app.telemetry.aspiration_signal_extractor import ASPIRATION_EXTRACT, AspirationSignalExtractor
from app.telemetry.curiosity_signal_extractor import CURIOSITY_EXTRACT, CuriositySignalExtractor
from app.telemetry.dashboard_builder import DashboardBuilder
from app.telemetry.dashboard_link_codec import DashboardLinkCodec, DashboardLinkSettings
from app.telemetry.status_report_builder import StatusReportBuilder, StatusSettings
from app.telemetry.student_dashboard_builder import StudentDashboardBuilder
from app.worker.child_session_summary_sender import ChildSessionSummarySender, SummaryDeps
from app.worker.database_step_recorder import DatabaseStepRecorder
from app.worker.khoj_card_sender import CardDeps, KhojCardSender
from app.worker.maintenance_loop import MaintenanceDeps, MaintenanceLoop, MaintenanceSettings
from app.worker.nudge_sender import NudgeSender, NudgeSettings, nudge_templates
from app.worker.outbox_loop import OutboxLoop, OutboxLoopSettings
from app.worker.post_turn_runner import PostTurnDeps, PostTurnRunner
from app.worker.reply_deliverer import DeliveryDeps, DeliverySettings, ReplyDeliverer
from app.worker.supervisor import Supervisor, SupervisorParts
from app.worker.turn_loop import TurnLoop, TurnLoopDeps, TurnLoopSettings
from app.worker.turn_processor import TurnDeps, TurnProcessor, TurnSettings

WORKER_ERROR_BACKOFF = timedelta(seconds=5)
PROVIDER_PROBE_TTL = timedelta(seconds=60)
QUEUE_STALL = timedelta(seconds=60)
READINESS_GREETING: Final = "Namaste, aaj ki khoj kya hai?"
ALEMBIC_INI: Final = Path(__file__).resolve().parents[1] / "alembic.ini"
LISTENER_HEALTH_CHECK = timedelta(seconds=15)
STREAM_HEARTBEAT = timedelta(seconds=15)  # s14 §4.4: a ping keeps proxies from closing the stream
STREAM_REPLAY_WINDOW = timedelta(minutes=2)
STREAMS_PER_VISITOR = 2
EVAL_JUDGE: Final = PromptSpec(prompt_id="eval_judge", output_type=JudgeScore)
"""Rendered only by `marg eval` (app/evals), over synthetic golden cases (s15 §4.4)."""
PROMPT_SPECS: Final = (
    PARENT_ANSWER,
    MINOR_POLICY,
    REPLY_POLICY,
    PROFILE_EXTRACTION,
    ACTIVITY_PERSONALISE,
    PARENT_REFLECTION,
    CURIOSITY_MOMENT,
    CHILD_TALK,
    CHILD_REDIRECT,
    CURIOSITY_EXTRACT,
    KHOJ_CARD_TEXT,
    QUERY_REWRITE,
    MEMORY,
    MENTOR,
    ROADMAP,
    ASPIRATION_EXTRACT,
    EXPOSURE,
    EVAL_JUDGE,
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
    image_segmenter: SamImageSegmenter
    rag: "RagParts"
    worker: Supervisor  # started by the api lifespan only when RUN_WORKER_IN_API
    listener_engine: AsyncEngine  # the one unpooled connection for LISTEN
    health_checks: "HealthChecks"  # the HTTP clients `/readyz` uses, closed on shutdown
    web_demo: WebDemoIngestor
    user_repository: UserRepository
    telemetry_pages: TelemetryPages
    turn_progress_hub: TurnProgressHub  # the web visitors' live traces (s14 §4.4)
    turn_event_stream: TurnEventStream
    progress_listener: NotificationListener  # LISTEN turn_progress for this api process


@dataclass(frozen=True, slots=True)
class OrchestratorPorts:
    language_model: LanguageModel
    safety_classifier: SafetyClassifier
    voice: VoiceSteps
    photos: PhotoSteps | None = None  # None while PHOTO_INPUT_ENABLED is false
    retriever: Retriever | None = None  # None: students get no mentor (tests that don't need it)


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
    retry = build_retry(clock)
    whatsapp_sender = WhatsAppSender(
        config=WhatsAppConfig(
            graph_base_url=str(settings.whatsapp_graph_base_url),
            phone_number_id=settings.whatsapp_phone_number_id,
            access_token=settings.whatsapp_access_token,
            timeout_s=settings.timeout_whatsapp_s,
        ),
        clock=clock,
    )
    providers = build_providers(settings, session_factory, retry, clock)
    inbox = InboxRepository(session_factory)
    outbox = OutboxRepository(session_factory)
    health_checks = build_health_checks(settings)
    listener_engine = create_listener_engine(settings.database_listen_url or settings.database_url)
    demo_repository = DemoRepository(session_factory)
    progress_hub = TurnProgressHub(
        demo_repository,
        StreamLimits(
            per_visitor=STREAMS_PER_VISITOR, per_process=settings.demo_sse_max_connections
        ),
    )
    worker = build_worker(
        settings=settings,
        session_factory=session_factory,
        listener_engine=listener_engine,
        engine_parts=build_engine_parts(
            settings,
            providers,
            EngineBasics(identity=identity, retry=retry, clock=clock, outbox=outbox),
            senders={Channel.WHATSAPP: whatsapp_sender, Channel.WEB: WebSender(clock)},
            catalogue=catalogue,
        ),
    )
    return Container(
        settings=settings,
        clock=clock,
        engine=engine,
        session_factory=session_factory,
        readiness_probes=(
            ReadinessProbe(name="database", critical=True, check=partial(ping, engine)),
            ReadinessProbe(name="schema", critical=True, check=partial(schema_is_current, engine)),
            ReadinessProbe(name="queue", critical=True, check=partial(queue_is_moving, inbox)),
            *provider_probes(settings, providers, health_checks, clock),
            # Voice degrades to text when these fail, so they don't take the app out of service
            ReadinessProbe(
                name="ffmpeg",
                critical=False,
                check=providers.voice_adapters.transcoder.check_encoders,
            ),
        ),
        health_checks=health_checks,
        identity=identity,
        whatsapp_sender=whatsapp_sender,
        inbox_repository=inbox,
        outbox_repository=outbox,
        language_models=(providers.spark, providers.open_model),
        safety_classifier=providers.safety_classifier,
        voice_adapters=providers.voice_adapters,
        image_generator=providers.image_generator,
        image_segmenter=providers.image_segmenter,
        rag=providers.rag,
        worker=worker,
        listener_engine=listener_engine,
        web_demo=WebDemoIngestor(
            DemoDeps(
                identity=identity,
                codec=SignedTokenCodec(
                    settings.session_signing_key, settings.session_signing_key_previous
                ),
                demo=demo_repository,
                media=providers.voice_adapters.media,
                inbox=inbox,
                waker=worker,
                clock=clock,
            ),
            DemoLimits(
                per_session_per_hour=settings.demo_rate_limit_per_hour,
                per_ip_per_hour=settings.demo_ip_rate_limit_per_hour,
                sessions_per_ip_per_hour=settings.demo_sessions_per_ip_per_hour,
                max_audio_bytes=settings.demo_max_audio_bytes,
                max_image_bytes=settings.demo_max_image_bytes,
                daily_cost_cap_usd=settings.daily_cost_cap_usd,
            ),
        ),
        user_repository=UserRepository(session_factory),
        telemetry_pages=build_telemetry_pages(settings, session_factory, clock),
        turn_progress_hub=progress_hub,
        turn_event_stream=TurnEventStream(
            progress_hub,
            demo_repository,
            StreamSettings(
                max_age=timedelta(seconds=settings.demo_sse_max_s),
                heartbeat=STREAM_HEARTBEAT,
                replay_window=STREAM_REPLAY_WINDOW,
            ),
        ),
        progress_listener=NotificationListener(
            listener_engine,
            {TURN_PROGRESS: progress_hub.on_notification},
            ListenerSettings(health_check_every=LISTENER_HEALTH_CHECK),
        ),
    )


@dataclass(frozen=True, slots=True)
class HealthChecks:
    model_api: HttpHealthCheck
    sidecar: HttpHealthCheck


def build_health_checks(settings: Settings) -> HealthChecks:
    return HealthChecks(
        model_api=HttpHealthCheck(
            HealthEndpoint(
                provider="meta_model_api",
                url=f"{str(settings.model_api_base_url).rstrip('/')}/models",
                token=settings.model_api_key,
                timeout_s=PROBE_TIMEOUT_S,
            )
        ),
        sidecar=HttpHealthCheck(
            HealthEndpoint(
                provider="ml_sidecar",
                url=f"{str(settings.sidecar_base_url).rstrip('/')}/healthz",
                token=settings.sidecar_token,
                timeout_s=PROBE_TIMEOUT_S,
            )
        ),
    )


def provider_probes(
    settings: Settings, providers: "Providers", checks: HealthChecks, clock: Clock
) -> tuple[ReadinessProbe, ...]:
    """s16 §4.3: the model API and safety are critical (without safety every reply is a holding
    reply); the ML sidecar isn't (text still goes out), and it is probed only when voice
    replies are on, since nothing else calls it. Each is cached so `/readyz` polling never
    hammers a paid or rate-limited API. WhatsApp has no probe: the messaging token can't read
    any object (owner checks a real reply instead, pre-demo checklist)."""

    async def safety_allows_a_greeting() -> None:
        verdict, _ = await providers.safety_classifier.classify(
            SafetyRequest(speaker="user", text=READINESS_GREETING, prior_user_text=None)
        )
        if verdict.categories:
            raise ProviderUnavailable("safety host flags a greeting", provider="llama_guard")

    probes = (
        ReadinessProbe(
            name="model_api",
            critical=True,
            check=CachedCheck(checks.model_api.check, PROVIDER_PROBE_TTL, clock),
        ),
        ReadinessProbe(
            name="safety",
            critical=True,
            check=CachedCheck(safety_allows_a_greeting, PROVIDER_PROBE_TTL, clock),
        ),
    )
    if not settings.voice_replies_enabled:
        return probes
    sidecar = ReadinessProbe(
        name="sidecar",
        critical=False,
        check=CachedCheck(checks.sidecar.check, PROVIDER_PROBE_TTL, clock),
    )
    return (*probes, sidecar)


async def schema_is_current(engine: AsyncEngine) -> None:
    """The database is at the newest migration bundled with this build."""
    head = ScriptDirectory.from_config(AlembicConfig(str(ALEMBIC_INI))).get_current_head()
    current = await schema_version(engine)
    if current != head:
        raise StoreError(f"schema at {current}, this build needs {head}")


async def queue_is_moving(inbox: InboxRepository) -> None:
    """The worker's liveness (s16 §4.3): no due message has waited a minute."""
    waited = await inbox.oldest_due_wait()
    if waited is not None and waited > QUEUE_STALL:
        raise StoreError(f"oldest message waiting {int(waited.total_seconds())} s")


def build_telemetry_pages(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession], clock: Clock
) -> TelemetryPages:
    """/status and the admin dashboard (s13 §4.7, §4.9)."""
    reader = TelemetryRepository(session_factory)
    return TelemetryPages(
        status=StatusReportBuilder(
            reader, clock, StatusSettings(web_daily_cap_usd=settings.daily_cost_cap_usd)
        ),
        dashboard=DashboardBuilder(reader, clock),
        students=StudentDashboardBuilder(reader, clock),
        links=dashboard_links(settings, clock),
        admin_floor=settings.k_anonymity_floor_admin,
        teacher_floor=settings.k_anonymity_floor,
    )


def dashboard_links(settings: Settings, clock: Clock) -> DashboardLinkCodec:
    """Shared by the pages and `marg admin-link`."""
    return DashboardLinkCodec(
        SignedTokenCodec(settings.session_signing_key, settings.session_signing_key_previous),
        clock,
        DashboardLinkSettings(
            link_ttl=timedelta(seconds=settings.dashboard_link_ttl_s),
            cookie_ttl=timedelta(seconds=settings.dashboard_cookie_ttl_s),
        ),
    )


def build_retry(clock: Clock) -> RetryPolicy:
    """The one retry policy every provider call shares (CLAUDE.md §12)."""
    return RetryPolicy(
        timing=RetryTiming(), clock=clock, sleeper=AsyncioSleeper(), rng=random.SystemRandom()
    )


@dataclass(frozen=True, slots=True)
class RagParts:
    """Retrieval over the corpus (s11): keyword search in Postgres, no model."""

    store: ChunkRepository
    retriever: Retriever


def build_rag(settings: Settings, session_factory: async_sessionmaker[AsyncSession]) -> RagParts:
    store = ChunkRepository(session_factory)
    retriever = Retriever(
        store,
        RetrieverSettings(
            top_k=settings.retrieval_top_k,
            min_text_rank=settings.retrieval_min_text_rank,
        ),
    )
    return RagParts(store, retriever)


def build_voice_adapters(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    retry: RetryPolicy,
    clock: Clock,
) -> VoiceAdapters:
    """Voice notes in (WhatsApp download, ffmpeg, Muse Voice Transcribe) and out (the voice
    server running TTS_ENGINE, ffmpeg). s06."""
    transcoder = AudioTranscoder(
        timeout_s=settings.transcode_timeout_s, voice_pitch=settings.tts_pitch
    )
    return VoiceAdapters(
        fetcher=WhatsAppMediaFetcher(
            config=MediaFetchConfig(
                graph_base_url=str(settings.whatsapp_graph_base_url),
                access_token=settings.whatsapp_access_token,
                timeout_s=settings.timeout_fetch_media_s,
                max_bytes=settings.max_inbound_audio_bytes,
                max_image_bytes=settings.max_inbound_image_bytes,
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
        fetcher=ChannelMediaFetcher(
            {Channel.WHATSAPP: adapters.fetcher, Channel.WEB: adapters.media}
        ),
        converter=adapters.transcoder,
        transcriber=adapters.transcriber,
        synthesizer=adapters.synthesizer,
        audio_store=adapters.media,
        limits=VoiceLimits(
            min_duration_ms=settings.min_voice_note_ms,
            min_voiced_ms=settings.min_voiced_ms,
            max_duration_ms=settings.max_voice_note_seconds * 1000,
        ),
        voice_replies_enabled=settings.voice_replies_enabled,
        reply_audio_for_text_input=settings.reply_audio_for_text_input,
    )


def photo_steps(
    settings: Settings, adapters: VoiceAdapters, segmenter: ImageSegmenter
) -> PhotoSteps | None:
    """Activity photos (s10b §4.14): the same per-channel fetcher as voice notes, and SAM 3.1."""
    if not settings.photo_input_enabled:
        return None
    return PhotoSteps(
        fetcher=ChannelMediaFetcher(
            {Channel.WHATSAPP: adapters.fetcher, Channel.WEB: adapters.media}
        ),
        segmenter=segmenter,
    )


def student_steps(
    settings: Settings,
    language_model: LanguageModel,
    registry: PromptRegistry,
    retriever: Retriever | None,
) -> StudentSteps | None:
    """The Aspirational layer (s12): the mentor and roadmap, over the corpus retriever."""
    if retriever is None:
        return None
    mentor = MentorLayer(
        language_model,
        registry,
        retriever,
        MentorSettings(query_rewrite_enabled=settings.query_rewrite_enabled),
    )
    return StudentSteps(
        mentor=mentor,
        roadmap=RoadmapLayer(language_model, registry, mentor),
        exposure=ExposureLayer(language_model, registry, ChapterCatalogue.load()),
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
                language_model,
                registry,
                invite_link=teacher_invite_link(settings),
                web_default_language=Language(settings.web_default_language),
            ),
            voice=ports.voice,
            child_talk=(
                ChildTalkLayer(language_model, registry, child_session_limits(settings))
                if settings.child_talk_enabled
                else None
            ),
            clock=clock,
            photos=ports.photos,
            student=student_steps(settings, language_model, registry, ports.retriever),
            dashboard_links=DashboardLinks(
                codec=dashboard_links(settings, clock), base_url=str(settings.public_base_url)
            ),
        ),
        OrchestratorSettings(
            turn_budget=timedelta(seconds=settings.turn_budget_s),
            safety_in_timeout=timedelta(seconds=settings.timeout_safety_in_s),
            generate_timeout=timedelta(seconds=settings.timeout_generate_s),
            exposure_timeout=timedelta(seconds=settings.timeout_exposure_s),
            mentor_timeout=timedelta(seconds=settings.timeout_mentor_s),
            safety_out_timeout=timedelta(seconds=settings.timeout_safety_out_s),
            fetch_media_timeout=timedelta(seconds=settings.timeout_fetch_media_s),
            transcribe_timeout=timedelta(seconds=settings.timeout_transcribe_s),
            synthesize_timeout=timedelta(seconds=settings.timeout_synthesize_s),
            fetch_image_timeout=timedelta(seconds=settings.timeout_fetch_image_s),
            analyze_image_timeout=timedelta(seconds=settings.timeout_analyze_image_s),
        ),
    )


def prompt_registry(settings: Settings) -> PromptRegistry:
    return PromptRegistry(
        specs=PROMPT_SPECS,
        settings=PromptSettings(
            models={
                "MODEL_TEXT": settings.model_text,
                "OPEN_MODEL": settings.open_model,
                "MODEL_JUDGE": settings.model_judge,
            },
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
    memory: MemoryLayer
    memory_model: LanguageModel  # the extraction model (Muse Spark Open with its fallback)


@dataclass(frozen=True, slots=True)
class Providers:
    """The adapters behind every port: the same for the app and for `marg eval`."""

    spark: MetaModelApiLanguageModel
    open_model: MetaModelApiLanguageModel
    language_model: FallbackLanguageModel  # Muse Spark Open, falling back to Spark
    safety_classifier: LlamaGuardClassifier
    voice_adapters: VoiceAdapters
    rag: RagParts
    image_generator: MuseImageGenerator
    image_segmenter: SamImageSegmenter


@dataclass(frozen=True, slots=True)
class EngineBasics:
    identity: UserIdentity
    retry: RetryPolicy
    clock: Clock
    outbox: OutboxRepository


def build_providers(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    retry: RetryPolicy,
    clock: Clock,
) -> Providers:
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
    rag = build_rag(settings, session_factory)
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
    image_segmenter = SamImageSegmenter(
        config=SegmentModelConfig(
            base_url=str(settings.model_api_base_url),
            api_key=settings.model_api_key,
            model=settings.model_segment,
            timeout_s=settings.timeout_analyze_image_s,
        ),
        retry=retry,
        clock=clock,
    )
    return Providers(
        spark=spark,
        open_model=open_model,
        language_model=language_model,
        safety_classifier=safety_classifier,
        voice_adapters=voice_adapters,
        rag=rag,
        image_generator=image_generator,
        image_segmenter=image_segmenter,
    )


def build_engine_parts(  # noqa: PLR0913  # the app and `marg eval` swap different parts
    settings: Settings,
    providers: Providers,
    basics: EngineBasics,
    *,
    senders: dict[Channel, ChannelSender],
    catalogue: ActivityCatalogue | None = None,
    synthesizer: Synthesizer | None = None,
    image_generator: ImageGenerator | None = None,
) -> EngineParts:
    """Everything the worker runs a turn with. `synthesizer` and `image_generator` replace the
    real ones (`marg eval` records instead of speaking or drawing)."""
    voice = voice_steps(settings, providers.voice_adapters)
    if synthesizer is not None:
        voice = replace(voice, synthesizer=synthesizer)
    registry = prompt_registry(settings)
    return EngineParts(
        clock=basics.clock,
        identity=basics.identity,
        retry=basics.retry,
        senders=senders,
        orchestrator=build_orchestrator(
            settings,
            OrchestratorPorts(
                providers.language_model,
                providers.safety_classifier,
                voice,
                photo_steps(settings, providers.voice_adapters, providers.image_segmenter),
                providers.rag.retriever,
            ),
            basics.clock,
            catalogue=catalogue,
        ),
        outbox=basics.outbox,
        media=providers.voice_adapters.media,
        signals=CuriositySignalExtractor(providers.language_model, registry),
        cards=(
            KhojCardMaker(providers.spark, image_generator or providers.image_generator, registry)
            if settings.khoj_card_enabled
            else None
        ),
        memory=MemoryLayer(providers.spark, registry),
        memory_model=providers.language_model,
    )


def build_worker(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    engine_parts: EngineParts,
    listener_engine: AsyncEngine | None,
) -> Supervisor:
    """The turn, outbox and maintenance loops (s04 §4.1). `listener_engine` None: no LISTEN,
    the loops poll every POLL_INTERVAL_S (tests)."""
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
    leases = LeaseRepository(
        session_factory,
        LeaseTimes(
            lease=timedelta(seconds=settings.lease_duration_s),
            debounce=timedelta(milliseconds=settings.turn_debounce_ms),
        ),
    )
    poll_interval = timedelta(seconds=settings.poll_interval_s)
    turn_loop = TurnLoop(
        TurnLoopDeps(
            processor=processor,
            deliverer=deliverer,
            leases=leases,
            post_turn=build_post_turn_runner(
                settings, session_factory, engine_parts, deliverer, worker_id
            ),
        ),
        TurnLoopSettings(
            worker_id=worker_id,
            concurrency=settings.worker_concurrency,
            lease=timedelta(seconds=settings.lease_duration_s),
            poll_interval=poll_interval,
            error_backoff=WORKER_ERROR_BACKOFF,
        ),
    )
    outbox_loop = OutboxLoop(
        engine_parts.outbox,
        deliverer,
        OutboxLoopSettings(
            concurrency=settings.outbox_concurrency,
            poll_interval=poll_interval,
            error_backoff=WORKER_ERROR_BACKOFF,
        ),
    )
    maintenance = MaintenanceLoop(
        MaintenanceDeps(
            leases=leases,
            outbox=engine_parts.outbox,
            turns=turns,
            users=users,
            media=engine_parts.media,
            child_sessions=ChildSessionRepository(session_factory),
            demo=DemoRepository(session_factory),
            summaries=ChildSessionSummarySender(
                SummaryDeps(
                    sessions=ChildSessionRepository(session_factory),
                    gate=engine_parts.orchestrator.steps.gate,
                    deliverer=deliverer,
                ),
                worker_id,
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
            clock=engine_parts.clock,
        ),
        MaintenanceSettings(
            interval=timedelta(seconds=settings.maintenance_interval_s),
            sending_stuck=timedelta(seconds=settings.outbox_sending_stuck_s),
            retain_turn_text=timedelta(days=settings.retention_turn_text_days),
            retain_raw_payload=timedelta(days=settings.retention_raw_payload_days),
            purge_sweep_after=timedelta(seconds=settings.purge_sweep_after_s),
            child_session_max=timedelta(minutes=settings.child_session_max_minutes),
        ),
    )
    listener = (
        NotificationListener(
            listener_engine,
            {
                "inbox_new": lambda _payload: turn_loop.wake.set(),
                "outbox_new": lambda _payload: outbox_loop.wake.set(),
            },
            ListenerSettings(health_check_every=LISTENER_HEALTH_CHECK),
        )
        if listener_engine is not None
        else None
    )
    return Supervisor(
        SupervisorParts(
            turns=turn_loop,
            outbox=outbox_loop,
            maintenance=maintenance,
            listener=listener,
            shutdown_grace=timedelta(seconds=settings.shutdown_grace_s),
        )
    )


def build_post_turn_runner(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    engine_parts: EngineParts,
    deliverer: ReplyDeliverer,
    worker_id: str,
) -> PostTurnRunner:
    signals = CuriositySignalRepository(session_factory)
    return PostTurnRunner(
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
            memory=engine_parts.memory,
            memories=ProfileMemoryRepository(session_factory),
            aspiration=AspirationSignalExtractor(
                engine_parts.memory_model, prompt_registry(settings)
            ),
            aspirations=AspirationSignalRepository(session_factory),
        )
    )


def build_judge_model(
    settings: Settings, retry: RetryPolicy, clock: Clock
) -> MetaModelApiLanguageModel:
    """`marg eval`'s judge (s15 §4.4): Muse Spark at high reasoning, with its own longer timeout."""
    return MetaModelApiLanguageModel(
        config=ModelApiConfig(
            base_url=str(settings.model_api_base_url),
            api_key=settings.model_api_key,
            timeout_s=settings.timeout_judge_s,
        ),
        retry=retry,
        clock=clock,
    )


async def close_providers(providers: Providers) -> None:
    """Release the HTTP clients `build_providers` opened (`marg eval`)."""
    for language_model in (providers.spark, providers.open_model):
        await language_model.aclose()
    await providers.safety_classifier.aclose()
    await providers.voice_adapters.fetcher.aclose()
    await providers.voice_adapters.transcriber.aclose()
    await providers.voice_adapters.synthesizer.aclose()
    await providers.image_generator.aclose()
    await providers.image_segmenter.aclose()


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
    await container.image_segmenter.aclose()
    await container.engine.dispose()
    await container.listener_engine.dispose()
    await container.health_checks.model_api.aclose()
    await container.health_checks.sidecar.aclose()
