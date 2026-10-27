import hashlib
import hmac
from itertools import permutations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import SecretStr

from app.channels.whatsapp.webhook_signature import WebhookSignatureVerifier
from app.core.errors import ConfigError, InvalidAddressCiphertext, SignatureInvalid
from app.core.user_identity import UserIdentity
from app.domain.enums import OutboxStatus
from app.domain.rules.delivery_planner import DeliveryPlanner
from tests.support.app_factory import (
    APP_SIGNING_KEY_FOR_TESTS,
    HANDSHAKE_WORD_FOR_TESTS,
    TEST_ENCRYPTION_KEY,
    TEST_SALT,
    make_identity,
)

pytestmark = pytest.mark.unit

SECRET = SecretStr(APP_SIGNING_KEY_FOR_TESTS)
BODY = b'{"object":"whatsapp_business_account"}'


def header_for(body: bytes, secret: str = APP_SIGNING_KEY_FOR_TESTS) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_signature_accepts_valid_hmac() -> None:
    WebhookSignatureVerifier.verify(BODY, header_for(BODY), SECRET)


def test_verify_signature_accepts_uppercase_hex() -> None:
    WebhookSignatureVerifier.verify(
        BODY, "sha256=" + header_for(BODY).removeprefix("sha256=").upper(), SECRET
    )


@pytest.mark.parametrize(
    ("header", "message"),
    [
        (None, "header is missing"),
        ("sha1=" + "0" * 40, "doesn't start with sha256="),
        ("sha256=" + "z" * 64, "isn't a 64-character hex digest"),
        ("sha256=" + "0" * 63, "isn't a 64-character hex digest"),
        ("sha256=" + "0" * 64, "doesn't match the body"),
        ("", "doesn't start with sha256="),
    ],
)
def test_verify_signature_rejects_bad_headers(header: str | None, message: str) -> None:
    with pytest.raises(SignatureInvalid, match=message):
        WebhookSignatureVerifier.verify(BODY, header, SECRET)


def test_verify_signature_rejects_wrong_secret() -> None:
    with pytest.raises(SignatureInvalid, match="doesn't match"):
        WebhookSignatureVerifier.verify(BODY, header_for(BODY, "another-secret"), SECRET)


def test_verify_signature_needs_the_raw_bytes() -> None:
    reformatted = b'{ "object": "whatsapp_business_account" }'
    with pytest.raises(SignatureInvalid, match="doesn't match"):
        WebhookSignatureVerifier.verify(reformatted, header_for(BODY), SECRET)


@given(
    body=st.binary(max_size=500),
    secret=st.text(min_size=1, max_size=40),
    flip=st.integers(0, 10_000),
)
def test_property_signature_verifies_and_any_flipped_byte_fails(
    body: bytes, secret: str, flip: int
) -> None:
    header = header_for(body, secret)
    WebhookSignatureVerifier.verify(body, header, SecretStr(secret))
    if body:
        position = flip % len(body)
        tampered = body[:position] + bytes([body[position] ^ 0x01]) + body[position + 1 :]
        with pytest.raises(SignatureInvalid):
            WebhookSignatureVerifier.verify(tampered, header, SecretStr(secret))
    digest_position = 7 + flip % 64
    flipped_char = "0" if header[digest_position] != "0" else "1"
    tampered_header = header[:digest_position] + flipped_char + header[digest_position + 1 :]
    with pytest.raises(SignatureInvalid):
        WebhookSignatureVerifier.verify(body, tampered_header, SecretStr(secret))


@pytest.mark.parametrize(
    ("mode", "token", "accepted"),
    [
        ("subscribe", HANDSHAKE_WORD_FOR_TESTS, True),
        ("subscribe", "wrong", False),
        ("unsubscribe", HANDSHAKE_WORD_FOR_TESTS, False),
        (None, HANDSHAKE_WORD_FOR_TESTS, False),
        ("subscribe", None, False),
        ("subscribe", "", False),
    ],
)
def test_verify_subscription(mode: str | None, token: str | None, *, accepted: bool) -> None:
    assert (
        WebhookSignatureVerifier.verify_subscription(
            mode, token, SecretStr(HANDSHAKE_WORD_FOR_TESTS)
        )
        is accepted
    )


# --- identity -----------------------------------------------------------------------------------


def test_user_hash_is_64_lowercase_hex() -> None:
    user_hash = make_identity().user_hash("whatsapp", "919000000001")
    assert len(user_hash) == 64
    assert user_hash == user_hash.lower()


def test_decrypt_with_another_users_hash_fails() -> None:
    identity = make_identity()
    ciphertext = identity.encrypt_address("a" * 64, "919000000001")
    with pytest.raises(InvalidAddressCiphertext, match="doesn't match this user"):
        identity.decrypt_address("b" * 64, ciphertext)


@pytest.mark.parametrize("ciphertext", [b"", b"short", b"\x00" * 12])
def test_decrypt_rejects_truncated_ciphertext(ciphertext: bytes) -> None:
    with pytest.raises(InvalidAddressCiphertext, match="too short"):
        make_identity().decrypt_address("a" * 64, ciphertext)


def test_decrypt_rejects_tampered_ciphertext() -> None:
    identity = make_identity()
    ciphertext = bytearray(identity.encrypt_address("a" * 64, "919000000001"))
    ciphertext[-1] ^= 0x01
    with pytest.raises(InvalidAddressCiphertext):
        identity.decrypt_address("a" * 64, bytes(ciphertext))


def test_same_address_encrypts_differently_each_time() -> None:
    identity = make_identity()
    assert identity.encrypt_address("a" * 64, "9190") != identity.encrypt_address("a" * 64, "9190")


@pytest.mark.parametrize(
    ("salt", "key", "message"),
    [
        ("not-hex", TEST_ENCRYPTION_KEY, "USER_HASH_SALT must be hex"),
        ("00" * 16, TEST_ENCRYPTION_KEY, "at least 32 bytes"),
        (TEST_SALT, "not base64!", "must be base64"),
        (TEST_SALT, "AAAA", "must decode to 32 bytes"),
    ],
)
def test_identity_rejects_bad_configuration(salt: str, key: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        UserIdentity(SecretStr(salt), SecretStr(key))


_DIGITS = st.text(alphabet="0123456789", min_size=8, max_size=15)


@given(address=_DIGITS, other=_DIGITS)
def test_property_identity(address: str, other: str) -> None:
    identity = make_identity()
    user_hash = identity.user_hash("whatsapp", address)
    assert identity.user_hash("whatsapp", address) == user_hash  # stable
    assert identity.user_hash("web", address) != user_hash  # channels never collide
    ciphertext = identity.encrypt_address(user_hash, address)
    assert identity.decrypt_address(user_hash, ciphertext).get_secret_value() == address
    assert address.encode() not in ciphertext
    if other != address:
        other_hash = identity.user_hash("whatsapp", other)
        assert other_hash != user_hash
        with pytest.raises(InvalidAddressCiphertext):
            identity.decrypt_address(other_hash, ciphertext)


# --- delivery status ordering ---------------------------------------------------------------


@pytest.mark.parametrize(
    "order", list(permutations([OutboxStatus.SENT, OutboxStatus.DELIVERED, OutboxStatus.READ]))
)
def test_any_arrival_order_ends_in_read(order: tuple[OutboxStatus, ...]) -> None:
    current = OutboxStatus.SENDING
    for reported in order:
        current = DeliveryPlanner.next_status(current, reported)
    assert current is OutboxStatus.READ


_STATUSES = st.sampled_from(list(OutboxStatus))


@given(current=_STATUSES, reported=_STATUSES)
def test_property_delivery_status_never_moves_backwards(
    current: OutboxStatus, reported: OutboxStatus
) -> None:
    result = DeliveryPlanner.next_status(current, reported)
    if OutboxStatus.FAILED in {current, reported}:
        assert result is OutboxStatus.FAILED
    else:
        order = [
            OutboxStatus.PENDING,
            OutboxStatus.SENDING,
            OutboxStatus.SENT,
            OutboxStatus.DELIVERED,
            OutboxStatus.READ,
        ]
        assert order.index(result) == max(order.index(current), order.index(reported))
