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
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.readiness import ReadinessProbe
from app.channels.whatsapp.whatsapp_sender import WhatsAppConfig, WhatsAppSender
from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.core.user_identity import UserIdentity
from app.domain.enums import Channel
from app.layers.parent_question_layer import PARENT_ANSWER, ParentQuestionLayer
from app.pipeline.fixed_reply_service import FixedReplyService
from app.pipeline.orchestrator import Orchestrator, OrchestratorSettings, PipelineSteps
from app.prompts.prompt_registry import PromptRegistry, PromptSettings
from app.providers.http import AsyncioSleeper, RetryPolicy, RetryTiming
from app.providers.llm.meta_model_api_language_model import (
    MetaModelApiLanguageModel,
    ModelApiConfig,
)
from app.providers.llm.model_pricing import ModelPricing
from app.providers.ports import ChannelSender, LanguageModel, SafetyClassifier
from app.providers.safety.llama_guard_classifier import LlamaGuardClassifier, SafetyHostConfig
from app.safety.domain_policy import MINOR_POLICY, DomainPolicy, PolicyModel
from app.safety.safety_gate import SafetyGate
from app.store.db import create_engine, create_session_factory, ping
from app.store.repositories.inbox_repository import InboxRepository
from app.store.repositories.outbox_repository import OutboxRepository
from app.store.repositories.turn_repository import TurnRepository
from app.store.repositories.turn_step_repository import TurnStepRepository
from app.worker.database_step_recorder import DatabaseStepRecorder
from app.worker.reply_deliverer import DeliveryDeps, DeliverySettings, ReplyDeliverer
from app.worker.turn_dispatcher import DispatcherDeps, DispatcherSettings, TurnDispatcher
from app.worker.turn_processor import TurnDeps, TurnProcessor, TurnSettings

DISPATCHER_ERROR_BACKOFF = timedelta(seconds=5)
PROMPT_SPECS: Final = (PARENT_ANSWER, MINOR_POLICY)
"""Every prompt the app renders; the registry refuses a template without a spec."""


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
    language_model: MetaModelApiLanguageModel
    safety_classifier: LlamaGuardClassifier
    turn_dispatcher: TurnDispatcher


def build_container(settings: Settings) -> Container:
    check_startup(settings)
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
    language_model = MetaModelApiLanguageModel(
        config=ModelApiConfig(
            base_url=str(settings.model_api_base_url),
            api_key=settings.model_api_key,
            timeout_s=settings.timeout_generate_s,
        ),
        retry=retry,
        clock=clock,
    )
    safety_classifier = LlamaGuardClassifier(
        config=SafetyHostConfig(
            base_url=str(settings.safety_base_url),
            api_key=settings.safety_api_key,
            model=settings.safety_model,
            timeout_s=settings.timeout_safety_in_s,
        ),
        retry=retry,
        clock=clock,
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
            orchestrator=build_orchestrator(settings, language_model, safety_classifier, clock),
            outbox=outbox,
        ),
    )
    return Container(
        settings=settings,
        clock=clock,
        engine=engine,
        session_factory=session_factory,
        readiness_probes=(
            ReadinessProbe(name="database", critical=True, check=partial(ping, engine)),
        ),
        identity=identity,
        whatsapp_sender=whatsapp_sender,
        inbox_repository=inbox,
        outbox_repository=outbox,
        language_model=language_model,
        safety_classifier=safety_classifier,
        turn_dispatcher=dispatcher,
    )


def check_startup(settings: Settings) -> None:
    """Fail the deploy, not a turn: raises ConfigError naming what's wrong."""
    ModelPricing.require_allowed_for_user_content(settings.model_text, "MODEL_TEXT")
    ModelPricing.price_of(settings.safety_model)
    FixedReplyService.check_all_languages()


def build_orchestrator(
    settings: Settings,
    language_model: LanguageModel,
    safety_classifier: SafetyClassifier,
    clock: Clock,
) -> Orchestrator:
    registry = PromptRegistry(
        specs=PROMPT_SPECS,
        settings=PromptSettings(
            models={"MODEL_TEXT": settings.model_text},
            reasoning_effort=settings.model_reasoning_effort,
            user_slot_max_chars=settings.user_slot_max_chars,
        ),
    )
    return Orchestrator(
        PipelineSteps(
            gate=SafetyGate(
                safety_classifier,
                DomainPolicy(
                    model=PolicyModel(language_model, registry)
                    if settings.safety_policy_model_enabled
                    else None
                ),
            ),
            parent_questions=ParentQuestionLayer(language_model, registry),
            clock=clock,
        ),
        OrchestratorSettings(
            turn_budget=timedelta(seconds=settings.turn_budget_s),
            safety_in_timeout=timedelta(seconds=settings.timeout_safety_in_s),
            generate_timeout=timedelta(seconds=settings.timeout_generate_s),
            safety_out_timeout=timedelta(seconds=settings.timeout_safety_out_s),
        ),
    )


@dataclass(frozen=True, slots=True)
class EngineParts:
    clock: Clock
    identity: UserIdentity
    retry: RetryPolicy
    senders: dict[Channel, ChannelSender]
    orchestrator: Orchestrator
    outbox: OutboxRepository


def build_turn_dispatcher(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    engine_parts: EngineParts,
) -> TurnDispatcher:
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
            worker_id=f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}",
            max_messages=settings.max_messages_per_turn,
            max_attempts=settings.max_turn_attempts,
            stale_after=timedelta(hours=settings.stale_message_hours),
            recent_exchanges=settings.recent_exchanges,
        ),
    )
    deliverer = ReplyDeliverer(
        DeliveryDeps(
            outbox=engine_parts.outbox,
            senders=engine_parts.senders,
            identity=engine_parts.identity,
            retry=engine_parts.retry,
            clock=engine_parts.clock,
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
            clock=engine_parts.clock,
        ),
        DispatcherSettings(
            debounce=timedelta(milliseconds=settings.turn_debounce_ms),
            maintenance_interval=timedelta(seconds=settings.maintenance_interval_s),
            shutdown_grace=timedelta(seconds=settings.shutdown_grace_s),
            retain_turn_text=timedelta(days=settings.retention_turn_text_days),
            retain_raw_payload=timedelta(days=settings.retention_raw_payload_days),
            error_backoff=DISPATCHER_ERROR_BACKOFF,
        ),
    )


async def close_container(container: Container) -> None:
    """Release what the container opened: HTTP connections and the database pool."""
    await container.whatsapp_sender.aclose()
    await container.language_model.aclose()
    await container.safety_classifier.aclose()
    await container.engine.dispose()
