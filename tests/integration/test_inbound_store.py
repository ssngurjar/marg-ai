"""Needs `make test-db-up` and migrations applied (`make test-int` does both)."""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.channels.whatsapp.payloads import WebhookBody
from app.channels.whatsapp.webhook_parser import WhatsAppWebhookParser
from app.core.types import JsonValue
from app.store.db import create_engine, create_session_factory
from app.store.repositories.inbox_repository import InboundRecord, InboxRepository
from tests.support import whatsapp_payloads as wa
from tests.support.app_factory import TEST_PHONE_NUMBER_ID, make_identity, make_settings

pytestmark = pytest.mark.integration

FIXED_RECEIVED_AT = datetime(2025, 10, 27, 8, 0, 2, tzinfo=UTC)


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL must point at the docker-compose.test.yml database")
    return url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(make_settings(database_url=database_url))
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE users, inbox_messages RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture
def store(engine: AsyncEngine) -> InboxRepository:
    return InboxRepository(create_session_factory(engine))


def records_for(
    payload: dict[str, JsonValue], received_at: datetime | None = None
) -> list[InboundRecord]:
    identity = make_identity()
    parsed = WhatsAppWebhookParser.parse(
        WebhookBody.model_validate(payload), TEST_PHONE_NUMBER_ID, identity,
        received_at or FIXED_RECEIVED_AT,
    )  # fmt: skip
    return [
        InboundRecord(
            message=item.inbound,
            address_ciphertext=identity.encrypt_address(
                item.inbound.user_hash, item.wa_id.get_secret_value()
            ),
            raw_payload=item.raw_payload,
        )
        for item in parsed.messages
    ]


async def count(engine: AsyncEngine, table: str) -> int:
    async with engine.connect() as connection:
        return int((await connection.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())  # noqa: S608  # table names are test constants


async def test_same_webhook_three_times_stores_once_and_notifies_once(
    engine: AsyncEngine, store: InboxRepository
) -> None:
    notifications: list[str] = []

    def on_notify(_connection: object, _pid: int, channel: str, _payload: str) -> None:
        notifications.append(channel)

    async with engine.connect() as listening:
        raw = await listening.get_raw_connection()
        driver = raw.driver_connection  # the asyncpg connection underneath
        assert driver is not None
        await driver.add_listener("inbox_new", on_notify)
        payload = wa.webhook([wa.text_message("hello")])
        stored = [(await store.save(records_for(payload))).stored for _ in range(3)]
        await asyncio.sleep(0.2)
        await driver.remove_listener("inbox_new", on_notify)
    assert stored == [1, 0, 0]
    assert await count(engine, "inbox_messages") == 1
    assert await count(engine, "users") == 1
    assert notifications == ["inbox_new"]


async def test_older_retry_keeps_the_newer_last_inbound_time(
    engine: AsyncEngine, store: InboxRepository
) -> None:
    newer = wa.text_message(message_id="wamid.NEW")
    newer["timestamp"] = "1761555600"  # one hour after SENT_AT
    await store.save(records_for(wa.webhook([newer])))
    await store.save(records_for(wa.webhook([wa.text_message(message_id="wamid.OLD")])))
    async with engine.connect() as connection:
        last_inbound = (
            await connection.execute(text("SELECT last_inbound_at FROM users"))
        ).scalar_one()
    assert last_inbound == datetime(2025, 10, 27, 9, 0, tzinfo=UTC)


async def test_no_column_anywhere_holds_the_number_or_name(
    engine: AsyncEngine, store: InboxRepository
) -> None:
    await store.save(
        records_for(wa.webhook([wa.text_message("hi"), wa.voice_note(), wa.image_message("cap")]))
    )
    async with engine.connect() as connection:
        for table in ("users", "inbox_messages"):
            rows = (await connection.execute(text(f"SELECT * FROM {table}"))).all()  # noqa: S608  # test constant
            dumped = repr(rows)
            assert wa.FAKE_WA_ID not in dumped
            assert wa.FAKE_WA_ID.encode().hex() not in dumped
            assert wa.PROFILE_NAME not in dumped


async def test_latest_message_and_address_round_trip(store: InboxRepository) -> None:
    await store.save(records_for(wa.webhook([wa.voice_note()])))
    latest = await store.latest_whatsapp_message()
    assert latest is not None
    assert latest.kind.value == "audio"
    ciphertext = await store.load_address(latest.user_hash)
    assert ciphertext is not None
    assert (
        make_identity().decrypt_address(latest.user_hash, ciphertext).get_secret_value()
        == wa.FAKE_WA_ID
    )


async def test_empty_inbox_has_no_latest_message(store: InboxRepository) -> None:
    assert await store.latest_whatsapp_message() is None


async def test_deleting_a_user_deletes_their_messages(
    engine: AsyncEngine, store: InboxRepository
) -> None:
    await store.save(records_for(wa.webhook([wa.text_message()])))
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM users"))
    assert await count(engine, "inbox_messages") == 0


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO users (user_hash, channel) VALUES ('not-a-hash', 'whatsapp')",
        "INSERT INTO users (user_hash, channel) VALUES (repeat('a', 64), 'telegram')",
        "INSERT INTO users (user_hash, channel, state) VALUES (repeat('a', 64), 'web', 'sleeping')",
    ],
)
async def test_check_constraints_reject_unknown_values(engine: AsyncEngine, statement: str) -> None:
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(text(statement))


async def test_empty_batch_is_a_no_op(engine: AsyncEngine, store: InboxRepository) -> None:
    result = await store.save([])
    assert result.stored == 0
    assert result.users_with_new_messages == frozenset()
    assert await count(engine, "users") == 0


async def test_received_at_is_kept(engine: AsyncEngine, store: InboxRepository) -> None:
    received = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)
    await store.save(records_for(wa.webhook([wa.text_message()]), received_at=received))
    async with engine.connect() as connection:
        stored = (
            await connection.execute(text("SELECT received_at FROM inbox_messages"))
        ).scalar_one()
    assert stored == received
    assert stored - received < timedelta(seconds=1)
