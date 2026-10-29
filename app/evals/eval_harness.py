"""EvalHarness: a disposable database and the real pipeline, wired for one eval run (s15 §4.2).

On entry it creates `marg_eval_<run id>` on the TEST Postgres, migrates it with the normal
migrations, loads the official-source corpus into it, and wires the production
orchestrator with real models and safety. Only text-to-speech and khoj-card pictures are
recorded instead of made (unless asked), and replies go to the web channel, so nothing reaches
WhatsApp. On exit it drops the database (unless keep_db), even after a crash.

A turn is played exactly as the web channel and the worker would: the message goes into the
inbox, the user's lease is taken, and the worker's own `process_user_turn` runs it with this
harness's observer; the reply is delivered and the post-turn work (memory, signals, a card)
runs before the next turn, so multi-turn cases see what a real user would.
"""

import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from types import TracebackType
from typing import ClassVar, Final, Self
from uuid import UUID, uuid4

from pydantic import SecretStr

from app.channels.web.web_sender import WebSender
from app.constants.onboarding_copy import COPY_VERSION
from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.core.errors import ConfigError, CorpusValidationError, StoreError
from app.core.user_identity import UserIdentity
from app.domain.enums import Channel, MessageKind
from app.domain.models.base import UserHash
from app.domain.models.message import AudioClip, ImageClip, InboundMessage, MediaRef
from app.evals.eval_context import EvalContext
from app.evals.eval_judge import EvalJudge
from app.evals.golden_case import GoldenCase, GoldenTurn
from app.evals.golden_case_loader import AUDIO_FIXTURES, IMAGE_FIXTURES
from app.evals.recording_image_generator import RecordingImageGenerator
from app.evals.recording_synthesizer import RecordingSynthesizer
from app.evals.turn_capture import TurnCapture, TurnRecord
from app.layers.activity_catalogue import ActivityCatalogue
from app.prompts.prompt_registry import PromptRegistry, PromptSettings
from app.providers.ports import LanguageModel
from app.rag.corpus_ingestor import CorpusIngestor
from app.rag.corpus_loader import CorpusLoader
from app.store.db import create_engine, create_session_factory
from app.store.eval_database import EvalDatabase
from app.store.repositories.eval_repository import (
    EvalRepository,
    EvalSeed,
    EvalTurnSnapshot,
    SeedActivity,
    SeedLearner,
)
from app.store.repositories.inbox_repository import InboundRecord, InboxRepository
from app.store.repositories.lease_repository import LeaseRepository, LeaseTimes
from app.store.repositories.media_blob_repository import MediaBlobRepository
from app.store.repositories.outbox_repository import OutboxRepository
from app.store.repositories.turn_repository import TurnRepository
from app.store.repositories.turn_step_repository import TurnStepRepository
from app.store.repositories.user_repository import UserRepository
from app.wiring import (
    EVAL_JUDGE,
    PROMPT_SPECS,
    EngineBasics,
    RagParts,
    build_engine_parts,
    build_judge_model,
    build_post_turn_runner,
    build_providers,
    build_retry,
    close_providers,
    prompt_registry,
)
from app.worker.database_step_recorder import DatabaseStepRecorder
from app.worker.post_turn_runner import PostTurnRunner
from app.worker.reply_deliverer import DeliveryDeps, DeliverySettings, ReplyDeliverer
from app.worker.turn_processor import TurnDeps, TurnProcessor, TurnSettings

WORKER_ID: Final = "marg-eval"
JUDGE_SLOT_MAX_CHARS: Final = 12000  # the reply and conversation the judge reads, whole
IMAGE_TYPES: Final = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
AUDIO_TYPES: Final = {".ogg": "audio/ogg", ".webm": "audio/webm", ".m4a": "audio/mp4"}


@dataclass(frozen=True, slots=True)
class HarnessOptions:
    with_tts: bool  # the real voice server instead of RecordingSynthesizer
    live_images: bool  # Muse Image instead of RecordingImageGenerator
    keep_db: bool  # leave the database for a look afterwards


class EvalHarness:
    MIGRATION_TIMEOUT: ClassVar[timedelta] = timedelta(minutes=3)

    def __init__(self, settings: Settings, options: HarnessOptions, run_id: str) -> None:
        """Raises ConfigError before touching anything when this isn't a test setup."""
        if settings.environment == "prod":
            raise ConfigError("marg eval never runs with ENVIRONMENT=prod")
        if settings.eval_database_admin_url is None:
            raise ConfigError("EVAL_DATABASE_ADMIN_URL is not set (the test Postgres)")
        self._settings = settings
        self._admin_url: SecretStr = settings.eval_database_admin_url
        self._options = options
        self._run_id = run_id
        self._database = f"marg_eval_{run_id}"
        self._clock: Clock = SystemClock()
        self._identity = UserIdentity(settings.user_hash_salt, settings.address_encryption_key)
        self.synthesizer = RecordingSynthesizer()
        self.images = RecordingImageGenerator()
        self._parts: _Wired | None = None

    async def __aenter__(self) -> Self:
        url = await EvalDatabase.create(self._admin_url, self._database)
        try:
            await EvalHarness.migrate(url, self.MIGRATION_TIMEOUT)
            # Voice replies on: the golden cases test the voice path (child talk answers by
            # voice), and the recording synthesizer calls no speech model unless --with-tts,
            # however VOICE_REPLIES_ENABLED is set for real users (off until MMS is cleared).
            wired_settings = self._settings.model_copy(
                update={"database_url": url, "voice_replies_enabled": True}
            )
            self._parts = self._wire(wired_settings)
            await self._ingest_corpus(self._parts)
        except BaseException:
            await self._close()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._close()

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def prompt_versions(self) -> dict[str, str]:
        return self._wired.prompt_versions

    def judge(self, repeat: int) -> EvalJudge:
        """The judge on MODEL_JUDGE at high reasoning effort (s15 §4.4)."""
        registry = PromptRegistry(
            specs=PROMPT_SPECS,
            settings=PromptSettings(
                models={
                    "MODEL_TEXT": self._settings.model_text,
                    "OPEN_MODEL": self._settings.open_model,
                    "MODEL_JUDGE": self._settings.model_judge,
                },
                reasoning_effort="high",
                user_slot_max_chars=JUDGE_SLOT_MAX_CHARS,
            ),
        )
        return EvalJudge(self._wired.judge_model, registry, EVAL_JUDGE, repeat)

    def user_for(self, case: GoldenCase) -> UserHash:
        return UserHash(self._identity.user_hash(Channel.WEB, f"eval-{case.id}-{self._run_id}"))

    async def seed(self, case: GoldenCase) -> UserHash:
        """The case's user, as onboarding would have left them."""
        user_hash = self.user_for(case)
        today = self._clock.now().date()
        profile = case.profile
        await self._wired.evals.seed(
            EvalSeed(
                user_hash=user_hash,
                role=profile.role if profile else None,
                grade=profile.grade if profile else None,
                subject=profile.subject if profile else None,
                district=profile.district if profile else None,
                language=profile.language if profile else None,
                learners=[
                    SeedLearner(
                        relation=child.relation,
                        nickname=child.nickname,
                        birth_year=today.year - child.age,  # their age this year
                        child_talk_consented=bool(case.child_talk_consent),
                    )
                    for child in case.children
                ],
                open_activity=self._offer(case.open_activity),
                consent_copy_version=COPY_VERSION,
            )
        )
        return user_hash

    async def play(
        self, case: GoldenCase, user_hash: UserHash, turn: GoldenTurn, *, first: bool
    ) -> TurnRecord:
        """One message in, one turn run, delivered, post-turn work done. Raises StoreError or
        ProviderError only for a harness failure (a provider failing inside the turn is a
        failed step, as in production)."""
        wired = self._wired
        message = await self._message(case, user_hash, turn, first=first)
        await wired.inbox.save(
            [InboundRecord(message=message, address_ciphertext=None, raw_payload=None)]
        )
        turn_key = f"{user_hash}:{message.external_id}"
        EvalContext.set(turn_key)
        if not await wired.leases.acquire(user_hash, WORKER_ID):
            raise StoreError(f"eval user {user_hash[:8]} is leased by another worker")
        capture = TurnCapture()
        turn_id = await wired.processor.process_user_turn(user_hash, capture)
        if turn_id is None:
            await wired.leases.release(user_hash, WORKER_ID)
            raise StoreError(f"eval turn for {case.id} picked no message")
        # Read the turn before delivering it: a confirmed deletion purges the user (and the
        # turn with them) once the reply is out (s08 §4.10).
        snapshot = await wired.evals.snapshot(turn_id)
        await wired.deliverer.deliver_turn(turn_id)
        await wired.post_turn.run(wired.processor.take_post_turn(turn_id))
        return await self._record(user_hash, snapshot, capture, turn_key)

    async def _record(
        self,
        user_hash: UserHash,
        snapshot: EvalTurnSnapshot,
        capture: TurnCapture,
        turn_key: str,
    ) -> TurnRecord:
        evals = self._wired.evals
        generated = capture.generated
        cited = [citation.chunk_id for citation in generated.citations] if generated else []
        return TurnRecord(
            snapshot=snapshot,
            safety_in=capture.safety_in,
            safety_out=capture.safety_out,
            generated=generated,
            spoken_texts=self.synthesizer.spoken_in(turn_key),
            sources=await evals.sources(cited),
            later_turns=await evals.turns_after(user_hash, snapshot.turn_id),
            media_left=await evals.stored_media(user_hash),
            card_prompts=self.images.prompts_in(turn_key),
        )

    async def _message(
        self, case: GoldenCase, user_hash: UserHash, turn: GoldenTurn, *, first: bool
    ) -> InboundMessage:
        """The inbox row exactly as the web channel would write it (s14 §4.3)."""
        media = self._wired.media
        kind = MessageKind.TEXT
        text: str | None = turn.user
        button: str | None = None
        ref: MediaRef | None = None
        if first and case.attachments:
            fixture = IMAGE_FIXTURES / case.attachments[0].fixture
            mime = IMAGE_TYPES.get(fixture.suffix.lower(), "image/jpeg")
            blob_id = await media.save_inbound_photo(
                user_hash, ImageClip(data=fixture.read_bytes(), mime_type=mime)
            )
            kind, ref = MessageKind.IMAGE, _media_ref(blob_id, mime)
        elif turn.audio_fixture is not None:
            fixture = AUDIO_FIXTURES / turn.audio_fixture
            mime = AUDIO_TYPES.get(fixture.suffix.lower(), "audio/ogg")
            blob_id = await media.save_inbound_audio(
                user_hash, AudioClip(data=fixture.read_bytes(), mime_type=mime, duration_ms=None)
            )
            kind, text, ref = MessageKind.AUDIO, None, _media_ref(blob_id, mime)
        elif turn.button is not None:
            kind, text, button = MessageKind.INTERACTIVE, None, turn.button
        now = self._clock.now()
        return InboundMessage(
            channel=Channel.WEB,
            external_id=str(uuid4()),
            user_hash=user_hash,
            kind=kind,
            text=text,
            media=ref,
            interactive_reply_id=button,
            provider_sent_at=now,
            received_at=now,
        )

    def _offer(self, activity_id: str | None) -> SeedActivity | None:
        if activity_id is None:
            return None
        for activity in self._wired.catalogue.enabled:
            if activity.id == activity_id:
                return SeedActivity(activity_id=activity.id, activity_version=activity.version)
        raise ConfigError(f"open_activity {activity_id!r} isn't an enabled activity")

    @staticmethod
    async def migrate(url: SecretStr, longest: timedelta) -> None:
        """The normal migrations, in a child process (alembic runs its own event loop).
        Raises StoreError when they fail or take longer than `longest`."""
        environment = {**os.environ, "DATABASE_URL": url.get_secret_value()}
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
            env=environment,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(longest.total_seconds()):
                _, errors = await process.communicate()
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise StoreError("eval database: migrations timed out") from exc
        if process.returncode != 0:
            last_line = errors.decode("utf-8", "replace").strip().splitlines()[-1:] or ["?"]
            raise StoreError(f"eval database: migrations failed ({last_line[0][:200]})")

    def _wire(self, settings: Settings) -> "_Wired":
        engine = create_engine(settings)
        sessions = create_session_factory(engine)
        retry = build_retry(self._clock)
        providers = build_providers(settings, sessions, retry, self._clock)
        outbox = OutboxRepository(sessions)
        catalogue = ActivityCatalogue.load()
        senders = {Channel.WEB: WebSender(self._clock)}
        parts = build_engine_parts(
            settings,
            providers,
            EngineBasics(identity=self._identity, retry=retry, clock=self._clock, outbox=outbox),
            senders=dict(senders),
            catalogue=catalogue,
            synthesizer=None if self._options.with_tts else self.synthesizer,
            image_generator=None if self._options.live_images else self.images,
        )
        deliverer = ReplyDeliverer(
            DeliveryDeps(
                outbox=outbox,
                users=UserRepository(sessions),
                senders=dict(senders),
                identity=self._identity,
                retry=retry,
                clock=self._clock,
                audio=providers.voice_adapters.media,
                images=providers.voice_adapters.media,
            ),
            DeliverySettings(
                max_attempts=settings.outbox_max_attempts,
                part_budget=timedelta(seconds=settings.turn_budget_s),
            ),
        )
        processor = TurnProcessor(
            TurnDeps(
                store=TurnRepository(sessions),
                recorder=DatabaseStepRecorder(TurnStepRepository(sessions)),
                run_turn=parts.orchestrator.run_turn,
                gate=parts.orchestrator.steps.gate,
                senders=dict(senders),
                clock=self._clock,
            ),
            TurnSettings(
                worker_id=WORKER_ID,
                max_messages=settings.max_messages_per_turn,
                max_attempts=settings.max_turn_attempts,
                stale_after=timedelta(hours=settings.stale_message_hours),
                recent_exchanges=settings.recent_exchanges,
            ),
        )
        judge_model = build_judge_model(settings, retry, self._clock)

        async def close_all() -> None:
            await close_providers(providers)
            await judge_model.aclose()

        return _Wired(
            engine_dispose=engine.dispose,
            providers_close=close_all,
            rag=providers.rag,
            processor=processor,
            deliverer=deliverer,
            post_turn=build_post_turn_runner(settings, sessions, parts, deliverer, WORKER_ID),
            leases=LeaseRepository(
                sessions,
                LeaseTimes(
                    lease=timedelta(seconds=settings.lease_duration_s), debounce=timedelta(0)
                ),
            ),
            inbox=InboxRepository(sessions),
            media=providers.voice_adapters.media,
            evals=EvalRepository(sessions),
            catalogue=catalogue,
            prompt_versions=prompt_registry(settings).versions,
            judge_model=judge_model,
        )

    async def _ingest_corpus(self, wired: "_Wired") -> None:
        """The real corpus: retrieval is part of what's measured."""
        try:
            files = CorpusLoader.load(self._clock.now().date())
            await CorpusIngestor(wired.rag.store).ingest(files, dry_run=False)
        except CorpusValidationError as exc:
            raise StoreError(f"eval corpus: {type(exc).__name__}: {exc}") from exc

    async def _close(self) -> None:
        if self._parts is not None:
            await self._parts.providers_close()
            await self._parts.engine_dispose()
            self._parts = None
        if not self._options.keep_db:
            await EvalDatabase.drop(self._admin_url, self._database)

    @property
    def _wired(self) -> "_Wired":
        if self._parts is None:
            raise ConfigError("the eval harness is used outside `async with`")
        return self._parts


@dataclass(frozen=True, slots=True)
class _Wired:
    engine_dispose: Callable[[], Awaitable[None]]
    providers_close: Callable[[], Awaitable[None]]
    rag: RagParts
    processor: TurnProcessor
    deliverer: ReplyDeliverer
    post_turn: PostTurnRunner
    leases: LeaseRepository
    inbox: InboxRepository
    media: MediaBlobRepository
    evals: EvalRepository
    catalogue: ActivityCatalogue
    prompt_versions: dict[str, str]
    judge_model: LanguageModel  # Muse Spark with the judge's own timeout


def _media_ref(blob_id: UUID, mime: str) -> MediaRef:
    return MediaRef(channel=Channel.WEB, provider_media_id=None, blob_id=blob_id, mime_type=mime)
