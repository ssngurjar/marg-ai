"""SignedTokenCodec: cookies and links that can't be forged or reused (s14 §4.2)."""

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import SecretStr

from app.core.signed_token_codec import SignedTokenCodec

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
CODEC = SignedTokenCodec(SecretStr("k" * 32))
MONTH = timedelta(days=30)


def issued(payload: dict[str, str] | None = None, at: datetime = NOW) -> str:
    return CODEC.issue("demo_session", payload or {"sid": "abc"}, at, MONTH)


@given(sid=st.text(min_size=1, max_size=40))
def test_a_token_verifies_back_to_its_payload(sid: str) -> None:
    verified = CODEC.verify(issued({"sid": sid}), "demo_session", NOW)
    assert verified is not None
    assert verified.payload == {"sid": sid}
    assert not verified.needs_refresh


@given(position=st.integers(min_value=0), replacement=st.sampled_from("AbZz09-_."))
def test_changing_any_single_character_fails(position: int, replacement: str) -> None:
    token = issued()
    index = position % len(token)
    tampered = token[:index] + replacement + token[index + 1 :]
    if tampered != token:
        assert CODEC.verify(tampered, "demo_session", NOW) is None


def test_a_session_cookie_is_never_accepted_as_a_dashboard_link() -> None:
    assert CODEC.verify(issued(), "dash", NOW) is None


def test_another_key_cant_verify_it() -> None:
    other = SignedTokenCodec(SecretStr("o" * 32))
    assert other.verify(issued(), "demo_session", NOW) is None


@pytest.mark.parametrize("token", ["", ".", "abc", "abc.", ".sig", "a.b.c"])
def test_malformed_tokens_are_none(token: str) -> None:
    assert CODEC.verify(token, "demo_session", NOW) is None


def test_an_expired_token_is_none_and_one_second_before_is_fine() -> None:
    token = issued()
    assert CODEC.verify(token, "demo_session", NOW + MONTH) is None
    assert CODEC.verify(token, "demo_session", NOW + MONTH - timedelta(seconds=1)) is not None


def test_a_token_from_the_future_beyond_five_minutes_is_none() -> None:
    future = issued(at=NOW + timedelta(minutes=6))
    assert CODEC.verify(future, "demo_session", NOW) is None
    assert CODEC.verify(issued(at=NOW + timedelta(minutes=4)), "demo_session", NOW) is not None


def test_a_week_old_token_asks_to_be_refreshed() -> None:
    verified = CODEC.verify(issued(at=NOW - timedelta(days=8)), "demo_session", NOW)
    assert verified is not None
    assert verified.needs_refresh


def test_after_rotation_the_previous_key_still_verifies_and_asks_for_a_refresh() -> None:
    rotated = SignedTokenCodec(SecretStr("n" * 32), previous_key=SecretStr("k" * 32))
    verified = rotated.verify(issued(), "demo_session", NOW)
    assert verified is not None
    assert verified.needs_refresh
