"""/status and /dashboard over HTTP (s13 §4.7, §4.9): who sees what, and how links fail."""

import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.telemetry_pages import TelemetryPages
from app.domain.enums import Channel
from app.domain.models.base import UserHash
from app.domain.models.learner import LearnerId
from app.domain.rules.curiosity_trajectory import CuriosityPoint
from app.main import create_app
from app.store.repositories.telemetry_repository import (
    ActivityCounts,
    JourneyCountsRow,
    StepLatencyRow,
    TurnSummaryRow,
    YoungLearnerData,
)
from app.telemetry.dashboard_builder import DashboardBuilder
from app.telemetry.dashboard_link_codec import ADMIN, teacher_claims
from app.telemetry.status_report_builder import StatusReportBuilder, StatusSettings
from app.telemetry.student_dashboard_builder import StudentDashboardBuilder
from app.wiring import dashboard_links
from tests.fakes.clock import FixedClock
from tests.fakes.telemetry_reader import FakeTelemetryReader
from tests.support.app_factory import make_container, make_settings

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
SETTINGS = make_settings()
NICKNAME = "Munni"  # must never appear on a page


def young(children: int) -> YoungLearnerData:
    data = YoungLearnerData()
    for number in range(1, children + 1):
        learner = LearnerId(UUID(int=number))
        data.owners[learner] = UserHash(f"{number:064x}")
        data.reports[learner] = [
            CuriosityPoint(NOW - timedelta(days=2), frozenset(), 2, child_asked_question=True)
        ]
        data.activities[learner] = ActivityCounts(offered=2, done=1, with_photo=0, with_counts=0)
    return data


def reader(*, broken: bool = False, children: int = 3) -> FakeTelemetryReader:
    return FakeTelemetryReader(
        steps=[StepLatencyRow("analyze_image", 4, 1800.0, 2600.0, 1.0, 0.0)],
        summary=TurnSummaryRow(8, 0.875, 5100.0, 9200.0, 1, 6, 0),
        journey=JourneyCountsRow(photos_received=4, photos_refused=1, cards_sent=2),
        costs={None: Decimal("0.3100"), Channel.WEB: Decimal("0.0500")},
        young=young(children),
        broken=broken,
    )


class ClientFactory(Protocol):
    def __call__(self, source: FakeTelemetryReader, admin_floor: int = 1) -> TestClient: ...


@pytest.fixture
def make_client() -> Iterator[ClientFactory]:
    clients: list[TestClient] = []

    def build(source: FakeTelemetryReader, admin_floor: int = 1) -> TestClient:
        clock = FixedClock(NOW)
        pages = TelemetryPages(
            status=StatusReportBuilder(source, clock, StatusSettings(Decimal(5))),
            dashboard=DashboardBuilder(source, clock),
            students=StudentDashboardBuilder(source, clock),
            links=dashboard_links(SETTINGS, clock),
            admin_floor=admin_floor,
            teacher_floor=5,
        )
        container = replace(make_container(settings=SETTINGS, clock=clock), telemetry_pages=pages)
        client = TestClient(create_app(container=container))
        client.__enter__()
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.__exit__(None, None, None)


def admin_link() -> str:
    return dashboard_links(SETTINGS, FixedClock(NOW)).link_token(ADMIN)


def logged_in(client: TestClient) -> TestClient:
    response = client.get(f"/dashboard?t={admin_link()}", follow_redirects=False)
    assert response.status_code == 303
    return client


# --- /status --------------------------------------------------------------------------------------


def test_status_is_public_and_shows_no_cost_or_crisis(make_client: ClientFactory) -> None:
    client = make_client(reader())
    page = client.get("/status")
    assert page.status_code == 200
    assert "Photos refused (a person in them)" in page.text
    assert "analyze_image" in page.text
    assert "Cost today" not in page.text
    assert "Crisis" not in page.text
    data = client.get("/status.json").json()
    assert data["admin"] is None
    assert data["journey"]["cards_sent"] == 2
    assert data["p50_user_ms"] == 5100


def test_status_with_the_admin_cookie_adds_cost_and_crisis(make_client: ClientFactory) -> None:
    client = logged_in(make_client(reader()))
    page = client.get("/status")
    assert "Cost today (IST)" in page.text
    assert "$0.3100" in page.text
    assert "$0.0500 of $5.00" in page.text
    assert client.get("/status.json").json()["admin"]["crisis_turns"] == 1


def test_status_is_503_when_the_database_is_down(make_client: ClientFactory) -> None:
    client = make_client(reader(broken=True))
    assert client.get("/status").status_code == 503
    assert client.get("/status.json").json() == {"error": "unavailable"}


# --- /dashboard ---------------------------------------------------------------------------------


def test_the_dashboard_without_a_link_or_cookie_is_401(make_client: ClientFactory) -> None:
    client = make_client(reader())
    page = client.get("/dashboard")
    assert page.status_code == 401
    assert "marg admin-link" in page.text
    assert client.get("/dashboard/data.json").status_code == 401


@pytest.mark.parametrize("token", ["garbage", "", "%%%", "a.b.c", "x" * 2000])
def test_a_bad_link_is_401_never_500(make_client: ClientFactory, token: str) -> None:
    response = make_client(reader()).get("/dashboard", params={"t": token}, follow_redirects=False)
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_a_good_link_becomes_a_cookie_and_leaves_the_address_bar(
    make_client: ClientFactory,
) -> None:
    client = make_client(reader())
    response = client.get(f"/dashboard?t={admin_link()}", follow_redirects=False)
    assert response.status_code == 303
    assert urlsplit(response.headers["location"]).query == ""
    cookie = response.headers["set-cookie"]
    assert "marg_dash=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Max-Age=7200" in cookie
    assert "Path=/" in cookie


def test_an_expired_link_is_401(make_client: ClientFactory) -> None:
    old = dashboard_links(SETTINGS, FixedClock(NOW - timedelta(minutes=16))).link_token(ADMIN)
    response = make_client(reader()).get(f"/dashboard?t={old}", follow_redirects=False)
    assert response.status_code == 401


def test_the_admin_dashboard_shows_the_young_learners(make_client: ClientFactory) -> None:
    client = logged_in(make_client(reader(children=3), admin_floor=1))
    page = client.get("/dashboard")
    assert page.status_code == 200
    assert "Children talking to Marg themselves" in page.text
    data = client.get("/dashboard/data.json").json()
    assert (data["young_learners"]["enough"], data["young_learners"]["children"]) == (True, 3)
    assert data["students"]["enough"] is False  # no student signals in this fixture
    assert "Students (6-12): aspirations" in page.text


def test_under_the_floor_the_dashboard_says_not_enough(make_client: ClientFactory) -> None:
    client = logged_in(make_client(reader(children=3), admin_floor=5))
    assert "Not enough learners yet (fewer than 5)" in client.get("/dashboard").text


def test_no_page_carries_a_hash_an_id_or_a_name(make_client: ClientFactory) -> None:
    client = logged_in(make_client(reader(children=6)))
    for path in ("/dashboard", "/dashboard/data.json", "/status", "/status.json"):
        text = client.get(path).text
        assert not re.search(r"[0-9a-f]{64}", text), path
        assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-", text), path
        assert NICKNAME not in text, path


def test_the_dashboard_is_503_when_the_database_is_down(make_client: ClientFactory) -> None:
    client = logged_in(make_client(reader(broken=True)))
    assert client.get("/dashboard").status_code == 503
    assert client.get("/dashboard/data.json").json() == {"error": "unavailable"}


def test_every_page_has_strict_security_headers_and_no_script(make_client: ClientFactory) -> None:
    client = logged_in(make_client(reader()))
    for path in ("/status", "/dashboard", "/dashboard/dashboard.css"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "default-src 'none'" in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "<script" not in response.text


def teacher_link() -> str:
    claims = teacher_claims("a" * 64, "Karauli")
    return dashboard_links(SETTINGS, FixedClock(NOW)).link_token(claims)


def test_a_teacher_sees_only_their_districts_students_at_the_normal_floor(
    make_client: ClientFactory,
) -> None:
    source = reader(children=6)
    client = make_client(source)
    assert client.get(f"/dashboard?t={teacher_link()}", follow_redirects=False).status_code == 303
    page = client.get("/dashboard")
    assert page.status_code == 200
    assert "Students in Karauli" in page.text
    assert "Young learners" not in page.text
    assert "Not enough students yet (fewer than 5)" in page.text
    assert source.districts[-1] == "Karauli"
    data = client.get("/dashboard/data.json").json()
    assert set(data) == {"students"}


def test_a_teacher_cookie_never_unlocks_admin_numbers_on_status(make_client: ClientFactory) -> None:
    client = make_client(reader())
    client.get(f"/dashboard?t={teacher_link()}", follow_redirects=False)
    assert client.get("/status.json").json()["admin"] is None
