"""Settings and containers for tests: every S3 field filled with test-only values."""

from collections.abc import Sequence

from pydantic import HttpUrl, SecretStr

from app.api.readiness import ReadinessProbe
from app.channels.whatsapp.client import WhatsAppConfig, WhatsAppSender
from app.core.clock import Clock, SystemClock
from app.core.config import Environment, Settings
from app.core.identity import UserIdentity
from app.store.db import create_engine, create_session_factory
from app.store.repositories.inbound import InboundStore
from app.store.repositories.outbox import OutboxStore
from app.wiring import Container

UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://marg:marg@127.0.0.1:1/marg"
TEST_SALT = "00" * 32  # test-only values; real ones live in .env
TEST_ENCRYPTION_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="  # 32 zero bytes, base64
APP_SIGNING_KEY_FOR_TESTS = "test-app-secret"
HANDSHAKE_WORD_FOR_TESTS = "test-verify-token"
TEST_PHONE_NUMBER_ID = "100000000000001"


def make_settings(
    *, database_url: str = UNREACHABLE_DATABASE_URL, environment: Environment = "test"
) -> Settings:
    return Settings(
        database_url=SecretStr(database_url),
        environment=environment,
        user_hash_salt=SecretStr(TEST_SALT),
        address_encryption_key=SecretStr(TEST_ENCRYPTION_KEY),
        whatsapp_graph_base_url=HttpUrl("https://graph.facebook.com/v26.0"),
        whatsapp_access_token=SecretStr("test-access-token"),
        whatsapp_app_secret=SecretStr(APP_SIGNING_KEY_FOR_TESTS),
        whatsapp_verify_token=SecretStr(HANDSHAKE_WORD_FOR_TESTS),
        whatsapp_phone_number_id=TEST_PHONE_NUMBER_ID,
    )


def make_identity() -> UserIdentity:
    return UserIdentity(SecretStr(TEST_SALT), SecretStr(TEST_ENCRYPTION_KEY))


def make_container(
    *,
    settings: Settings | None = None,
    probes: Sequence[ReadinessProbe] = (),
    inbound_store: InboundStore | None = None,
    outbox_store: OutboxStore | None = None,
    clock: Clock | None = None,
) -> Container:
    """A container with real (unconnected) adapters; tests replace what they need."""
    resolved = settings or make_settings()
    engine = create_engine(resolved)
    session_factory = create_session_factory(engine)
    resolved_clock = clock or SystemClock()
    return Container(
        settings=resolved,
        clock=resolved_clock,
        engine=engine,
        session_factory=session_factory,
        readiness_probes=tuple(probes),
        identity=make_identity(),
        whatsapp_sender=WhatsAppSender(
            config=WhatsAppConfig(
                graph_base_url=str(resolved.whatsapp_graph_base_url),
                phone_number_id=resolved.whatsapp_phone_number_id,
                access_token=resolved.whatsapp_access_token,
                timeout_s=resolved.timeout_whatsapp_s,
            ),
            clock=resolved_clock,
        ),
        inbound_store=inbound_store or InboundStore(session_factory),
        outbox_store=outbox_store or OutboxStore(session_factory),
    )
