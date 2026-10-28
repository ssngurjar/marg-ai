"""DashboardLinkCodec: signed admin links (s13 §4.9). Any problem is LinkInvalid."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from app.core.errors import LinkInvalid
from app.core.signed_token_codec import SignedTokenCodec
from app.telemetry.dashboard_link_codec import ADMIN, DashboardLinkCodec, DashboardLinkSettings
from tests.fakes.clock import FixedClock

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)
KEY = SecretStr("dashboard-test-signing-key-0123456789")
SETTINGS = DashboardLinkSettings(link_ttl=timedelta(minutes=15), cookie_ttl=timedelta(hours=2))


def codec_at(moment: datetime, key: SecretStr = KEY) -> DashboardLinkCodec:
    return DashboardLinkCodec(SignedTokenCodec(key), FixedClock(moment), SETTINGS)


def test_an_admin_link_reads_back_as_admin() -> None:
    codec = codec_at(NOW)
    assert codec.read(codec.link_token(ADMIN)) == ADMIN
    assert codec.read(codec.cookie_token(ADMIN)) == ADMIN


def test_a_link_works_until_its_fifteen_minutes_are_up_exactly() -> None:
    token = codec_at(NOW).link_token(ADMIN)
    assert codec_at(NOW + timedelta(minutes=15) - timedelta(seconds=1)).read(token) == ADMIN
    with pytest.raises(LinkInvalid, match="dashboard token rejected"):
        codec_at(NOW + timedelta(minutes=15)).read(token)


def test_the_cookie_lasts_two_hours() -> None:
    token = codec_at(NOW).cookie_token(ADMIN)
    assert codec_at(NOW + timedelta(hours=2) - timedelta(seconds=1)).read(token) == ADMIN
    with pytest.raises(LinkInvalid):
        codec_at(NOW + timedelta(hours=2)).read(token)


@pytest.mark.parametrize("position", [0, 10, -1])
def test_any_changed_character_is_rejected(position: int) -> None:
    token = codec_at(NOW).link_token(ADMIN)
    flipped = "A" if token[position] != "A" else "B"
    tampered = (
        token[:position] + flipped + token[position + 1 :]
        if position != -1
        else token[:-1] + flipped
    )
    with pytest.raises(LinkInvalid):
        codec_at(NOW).read(tampered)


def test_a_web_demo_session_token_is_never_a_dashboard_token() -> None:
    session = SignedTokenCodec(KEY).issue("demo_session", {"sid": "abc"}, NOW, timedelta(days=1))
    with pytest.raises(LinkInvalid):
        codec_at(NOW).read(session)


def test_a_token_signed_with_another_key_is_rejected() -> None:
    token = codec_at(NOW, SecretStr("another-key-entirely-0123456789ab")).link_token(ADMIN)
    with pytest.raises(LinkInvalid):
        codec_at(NOW).read(token)


@pytest.mark.parametrize(
    "payload",
    [
        {"v": "1", "scope": "teacher", "sub": "admin"},
        {"v": "2", "scope": "admin", "sub": "admin"},
        {"v": "1", "scope": "admin", "sub": "admin", "district": "Karauli"},
        {},
    ],
    ids=["teacher_scope", "unknown_version", "extra_claim", "empty"],
)
def test_claims_this_version_doesnt_know_are_rejected(payload: dict[str, str]) -> None:
    token = SignedTokenCodec(KEY).issue("dash", payload, NOW, timedelta(minutes=15))
    with pytest.raises(LinkInvalid, match="unknown claims"):
        codec_at(NOW).read(token)


@pytest.mark.parametrize("token", ["", "garbage", "a.b", "....", "%%%.%%%"])
def test_malformed_tokens_are_rejected_not_errors(token: str) -> None:
    with pytest.raises(LinkInvalid):
        codec_at(NOW).read(token)
