"""`marg admin-link`: a 15-minute admin dashboard link, printed to this terminal (s13 §4.9)."""

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from app import cli
from app.core.clock import SystemClock
from app.telemetry.dashboard_link_codec import ADMIN
from app.wiring import dashboard_links
from tests.support.app_factory import make_settings

pytestmark = pytest.mark.unit

SETTINGS = make_settings()


def printed_link(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out.splitlines()[0]


@pytest.mark.parametrize("base_url", ["https://marg.example", "https://marg.example/"])
def test_the_printed_link_opens_the_admin_dashboard(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], base_url: str
) -> None:
    monkeypatch.setattr(cli, "load_settings", lambda: SETTINGS)
    assert cli.main(["admin-link", "--base-url", base_url]) == cli.EXIT_OK
    link = urlsplit(printed_link(capsys))
    assert (link.scheme, link.netloc, link.path) == ("https", "marg.example", "/dashboard")
    [token] = parse_qs(link.query)["t"]
    assert dashboard_links(SETTINGS, SystemClock()).read(token) == ADMIN


def test_without_a_base_url_the_setting_is_used(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "load_settings", lambda: SETTINGS)
    cli.main(["admin-link"])
    assert printed_link(capsys).startswith("http://127.0.0.1:8000/dashboard?t=")


def test_the_link_expires_after_the_configured_minutes() -> None:
    assert SETTINGS.dashboard_link_ttl_s == int(timedelta(minutes=15).total_seconds())
