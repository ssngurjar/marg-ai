import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime

import pytest
import structlog
from fastapi.testclient import TestClient

from app.core.errors import StoreError
from app.core.types import JsonValue
from app.domain.enums import OutboxStatus
from app.domain.models.base import UserHash
from app.main import create_app
from app.store.repositories.inbox_repository import InboundRecord, InboxRepository, SaveResult
from app.store.repositories.outbox_repository import OutboxRepository
from app.worker.turn_dispatcher import TurnDispatcher
from tests.support import whatsapp_payloads as wa
from tests.support.app_factory import (
    HANDSHAKE_WORD_FOR_TESTS,
    make_container,
    make_identity,
    make_settings,
)

pytestmark = pytest.mark.unit

URL = "/webhooks/whatsapp"


class RecordingStore(InboxRepository):
    """Captures what the route would store; optionally fails like a down database."""

    def __init__(self, *, fail: bool = False) -> None:
        self.saved: list[InboundRecord] = []
        self.calls = 0
        self.fail = fail

    async def save(self, records: Sequence[InboundRecord]) -> SaveResult:
        self.calls += 1
        if self.fail:
            raise StoreError("could not store inbound messages: OperationalError")
        self.saved.extend(records)
        users = frozenset(record.message.user_hash for record in records)
        return SaveResult(stored=len(records), users_with_new_messages=users)


class RecordingDispatcher(TurnDispatcher):
    """Records wake-ups instead of running turns; nothing to start or stop."""

    def __init__(self) -> None:  # deliberately skips the real dependencies
        self.woken: list[UserHash] = []

    def wake(self, user_hash: UserHash) -> None:
        self.woken.append(user_hash)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class AppliedStatus:
    provider_message_id: str
    status: OutboxStatus
    error_code: int | None


class RecordingOutbox(OutboxRepository):
    """Captures status updates; `ours` lists the provider ids that match an outbox row."""

    def __init__(self, *, ours: frozenset[str] = frozenset(), fail: bool = False) -> None:
        self.applied: list[AppliedStatus] = []
        self.ours = ours
        self.fail = fail

    async def apply_status_update(
        self, provider_message_id: str, reported: OutboxStatus, at: datetime, error_code: int | None
    ) -> bool:
        if self.fail:
            raise StoreError("could not apply a status update: OperationalError")
        self.applied.append(AppliedStatus(provider_message_id, reported, error_code))
        return provider_message_id in self.ours


@contextmanager
def client_with(
    store: RecordingStore,
    outbox: RecordingOutbox | None = None,
    dispatcher: RecordingDispatcher | None = None,
) -> Iterator[TestClient]:
    structlog.reset_defaults()
    container = replace(
        make_container(inbox_repository=store, outbox_repository=outbox or RecordingOutbox()),
        turn_dispatcher=dispatcher or RecordingDispatcher(),
    )
    with TestClient(create_app(container=container)) as client:
        yield client


def post(client: TestClient, raw: bytes, signature: str | None) -> int:
    headers = {"content-type": "application/json"}
    if signature is not None:
        headers["x-hub-signature-256"] = signature
    return client.post(URL, content=raw, headers=headers).status_code


# --- GET handshake --------------------------------------------------------------------------


def test_handshake_echoes_challenge_for_our_token() -> None:
    with client_with(RecordingStore()) as client:
        response = client.get(
            URL,
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": HANDSHAKE_WORD_FOR_TESTS,
                "hub.challenge": "1158201444",
            },
        )
    assert response.status_code == 200
    assert response.text == "1158201444"
    assert response.headers["content-type"].startswith("text/plain")


@pytest.mark.parametrize(
    "params",
    [
        {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"},
        {
            "hub.mode": "unsubscribe",
            "hub.verify_token": HANDSHAKE_WORD_FOR_TESTS,
            "hub.challenge": "1",
        },
        {"hub.mode": "subscribe", "hub.verify_token": HANDSHAKE_WORD_FOR_TESTS},
        {},
    ],
)
def test_handshake_rejected_otherwise(params: dict[str, str]) -> None:
    with client_with(RecordingStore()) as client:
        response = client.get(URL, params=params)
    assert response.status_code == 403
    assert response.text == ""


# --- POST -------------------------------------------------------------------------------------


def test_valid_webhook_stores_message_with_encrypted_address() -> None:
    store = RecordingStore()
    raw, signature = wa.signed(wa.webhook([wa.text_message("hello")]))
    with client_with(store) as client:
        response = client.post(URL, content=raw, headers={"x-hub-signature-256": signature})
    assert response.status_code == 200
    assert response.text == "ok"
    [record] = store.saved
    identity = make_identity()
    assert record.message.user_hash == identity.user_hash("whatsapp", wa.FAKE_WA_ID)
    assert record.address_ciphertext is not None
    decrypted = identity.decrypt_address(record.message.user_hash, record.address_ciphertext)
    assert decrypted.get_secret_value() == wa.FAKE_WA_ID


@pytest.mark.parametrize("signature", [None, "sha256=" + "0" * 64, "garbage"])
def test_bad_signature_is_401_and_stores_nothing(signature: str | None) -> None:
    store = RecordingStore()
    raw, _ = wa.signed(wa.webhook([wa.text_message()]))
    with client_with(store) as client:
        assert post(client, raw, signature) == 401
    assert store.calls == 0


def test_signature_from_another_secret_is_401() -> None:
    store = RecordingStore()
    another_apps_key = "not-our-app-signing-key"
    raw, signature = wa.signed(wa.webhook([wa.text_message()]), another_apps_key)
    with client_with(store) as client:
        assert post(client, raw, signature) == 401
    assert store.calls == 0


@pytest.mark.parametrize("raw", [b"not json", b'{"object": "whatsapp_business_account"}', b"[]"])
def test_authentic_but_unparseable_is_200_and_stores_nothing(raw: bytes) -> None:
    store = RecordingStore()
    body, signature = wa.signed(raw)
    with client_with(store) as client:
        assert post(client, body, signature) == 200
    assert store.saved == []


def test_oversized_body_is_413() -> None:
    store = RecordingStore()
    small_limit = make_settings().model_copy(update={"webhook_max_body_bytes": 100})
    container = make_container(settings=small_limit, inbox_repository=store)
    raw, signature = wa.signed(wa.webhook([wa.text_message("x" * 200)]))
    with TestClient(create_app(container=container)) as client:
        assert post(client, raw, signature) == 413
    assert store.calls == 0


def test_database_down_is_503_so_meta_retries() -> None:
    raw, signature = wa.signed(wa.webhook([wa.text_message()]))
    with client_with(RecordingStore(fail=True)) as client:
        assert post(client, raw, signature) == 503


def test_account_update_is_200_logged_as_received_and_stores_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload: dict[str, JsonValue] = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WABA1", "changes": [wa.account_update_change()]}],
    }
    raw, signature = wa.signed(payload)
    store = RecordingStore()
    with client_with(store) as client:
        assert post(client, raw, signature) == 200
    assert store.saved == []
    logged = capsys.readouterr().out
    assert "webhook_received" in logged
    assert "webhook_unparseable" not in logged


def test_status_webhooks_are_applied_to_the_outbox_not_stored() -> None:
    store = RecordingStore()
    outbox = RecordingOutbox(ours=frozenset({"wamid.OUT1"}))
    raw, signature = wa.signed(
        wa.webhook(
            statuses=[
                wa.status("delivered"),
                wa.status("failed", message_id="wamid.OTHER", error_code=131047),
            ]
        )
    )
    with client_with(store, outbox) as client:
        assert post(client, raw, signature) == 200
    assert store.saved == []
    assert outbox.applied == [
        AppliedStatus("wamid.OUT1", OutboxStatus.DELIVERED, None),
        AppliedStatus("wamid.OTHER", OutboxStatus.FAILED, 131047),
    ]


def test_status_store_down_is_503_so_meta_retries() -> None:
    raw, signature = wa.signed(wa.webhook(statuses=[wa.status("read")]))
    with client_with(RecordingStore(), RecordingOutbox(fail=True)) as client:
        assert post(client, raw, signature) == 503


def test_foreign_number_and_statuses_store_nothing() -> None:
    store = RecordingStore()
    with client_with(store) as client:
        for payload in (
            wa.webhook([wa.text_message()], phone_number_id="999"),
            wa.webhook(statuses=[wa.status("delivered")]),
        ):
            raw, signature = wa.signed(payload)
            assert post(client, raw, signature) == 200
    assert store.saved == []


def test_logs_never_contain_number_name_or_message(capsys: pytest.CaptureFixture[str]) -> None:
    store = RecordingStore()
    raw, signature = wa.signed(wa.webhook([wa.text_message("mera beta doctor banega")]))
    unparseable, unparseable_signature = wa.signed(
        b'{"object": 42, "entry": "' + wa.FAKE_WA_ID.encode() + b'"}'
    )
    with client_with(store) as client:
        post(client, raw, signature)
        post(client, unparseable, unparseable_signature)
        post(client, raw, "sha256=" + "0" * 64)
    output = capsys.readouterr().out
    assert "webhook_received" in output
    for private in (wa.FAKE_WA_ID, wa.PROFILE_NAME, "mera beta doctor banega"):
        assert private not in output
    for line in filter(None, output.splitlines()):
        json.loads(line)  # every line is structured JSON


def test_a_stored_message_wakes_its_sender_once() -> None:
    store = RecordingStore()
    dispatcher = RecordingDispatcher()
    raw, signature = wa.signed(wa.webhook([wa.text_message()]))
    with client_with(store, dispatcher=dispatcher) as client:
        assert post(client, raw, signature) == 200
    assert dispatcher.woken == [store.saved[0].message.user_hash]


def test_nothing_is_woken_when_storing_fails() -> None:
    dispatcher = RecordingDispatcher()
    raw, signature = wa.signed(wa.webhook([wa.text_message()]))
    with client_with(RecordingStore(fail=True), dispatcher=dispatcher) as client:
        assert post(client, raw, signature) == 503
    assert dispatcher.woken == []
