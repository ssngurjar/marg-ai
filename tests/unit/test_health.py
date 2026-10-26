import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.readiness import ReadinessProbe
from app.core.clock import SystemClock
from app.core.config import Settings
from app.core.errors import StoreError
from app.main import create_app
from app.store.db import create_engine, create_session_factory
from app.wiring import Container

pytestmark = pytest.mark.unit

UNREACHABLE_URL = "postgresql+asyncpg://marg:marg@127.0.0.1:1/marg"


async def passing() -> None:
    return None


async def failing() -> None:
    raise StoreError("database ping failed: OSError")


async def hanging() -> None:
    await asyncio.sleep(10)


@contextmanager
def make_client(*probes: ReadinessProbe) -> Iterator[TestClient]:
    settings = Settings(database_url=SecretStr(UNREACHABLE_URL), environment="test")
    engine = create_engine(settings)
    container = Container(
        settings=settings,
        clock=SystemClock(),
        engine=engine,
        session_factory=create_session_factory(engine),
        readiness_probes=probes,
    )
    with TestClient(create_app(container=container)) as client:
        yield client


@pytest.fixture
def ready_client() -> Iterator[TestClient]:
    with make_client(ReadinessProbe(name="database", critical=True, check=passing)) as client:
        yield client


def test_healthz_returns_ok(ready_client: TestClient) -> None:
    response = ready_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_ready_when_all_critical_probes_pass(ready_client: TestClient) -> None:
    response = ready_client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "environment": "test",
        "checks": [{"name": "database", "ok": True, "detail": None, "critical": True}],
    }


def test_readyz_not_ready_when_database_probe_fails() -> None:
    with make_client(ReadinessProbe(name="database", critical=True, check=failing)) as client:
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["status"] == "not_ready"
        assert response.json()["checks"] == [
            {
                "name": "database",
                "ok": False,
                "detail": "database ping failed: OSError",
                "critical": True,
            }
        ]


def test_readyz_probe_timeout_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.readiness.PROBE_TIMEOUT_S", 0.05)
    probes = (
        ReadinessProbe(name="slow", critical=True, check=hanging),
        ReadinessProbe(name="database", critical=True, check=passing),
    )
    with make_client(*probes) as client:
        response = client.get("/readyz")
        assert response.status_code == 503
        checks = {check["name"]: check for check in response.json()["checks"]}
        assert checks["slow"] == {
            "name": "slow",
            "ok": False,
            "detail": "timeout",
            "critical": True,
        }
        assert checks["database"]["ok"] is True


def test_readyz_noncritical_failure_still_ready() -> None:
    probes = (
        ReadinessProbe(name="database", critical=True, check=passing),
        ReadinessProbe(name="sidecar", critical=False, check=failing),
    )
    with make_client(*probes) as client:
        response = client.get("/readyz")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"
        assert response.json()["checks"][1]["ok"] is False


def test_readyz_with_no_probes_is_ready() -> None:
    with make_client() as client:
        assert client.get("/readyz").json() == {
            "status": "ready",
            "environment": "test",
            "checks": [],
        }


def test_docs_hidden_in_prod() -> None:
    settings = Settings(database_url=SecretStr(UNREACHABLE_URL), environment="prod")
    engine = create_engine(settings)
    container = Container(settings, SystemClock(), engine, create_session_factory(engine), ())
    with TestClient(create_app(container=container)) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
