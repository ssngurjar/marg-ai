"""Settings and containers for tests: every S3 field filled with test-only values."""

from collections.abc import Sequence
from dataclasses import replace

from pydantic import HttpUrl, SecretStr

from app.api.readiness import ReadinessProbe
from app.core.clock import Clock
from app.core.config import Environment, Settings
from app.core.user_identity import UserIdentity
from app.store.repositories.inbox_repository import InboxRepository
from app.store.repositories.outbox_repository import OutboxRepository
from app.wiring import Container, build_container

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
        model_api_base_url=HttpUrl("https://api.meta.ai/v1"),
        model_api_key=SecretStr("test-model-key"),
        safety_base_url=HttpUrl("https://guard.example/v1"),
        safety_api_key=SecretStr("test-guard-key"),
        safety_model="meta-llama/Llama-Guard-4-12B",
    )


def make_identity() -> UserIdentity:
    return UserIdentity(SecretStr(TEST_SALT), SecretStr(TEST_ENCRYPTION_KEY))


def make_container(
    *,
    settings: Settings | None = None,
    probes: Sequence[ReadinessProbe] = (),
    inbox_repository: InboxRepository | None = None,
    outbox_repository: OutboxRepository | None = None,
    clock: Clock | None = None,
) -> Container:
    """The production container (unconnected), with the parts a test replaces swapped in."""
    built = build_container(settings or make_settings())
    return replace(
        built,
        readiness_probes=tuple(probes),
        identity=make_identity(),
        inbox_repository=inbox_repository or built.inbox_repository,
        outbox_repository=outbox_repository or built.outbox_repository,
        clock=clock or built.clock,
    )
