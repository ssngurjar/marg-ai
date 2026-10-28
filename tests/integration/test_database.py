"""Needs `make test-db-up` (docker-compose.test.yml) and DATABASE_URL pointing at it."""

import os

import pytest
from fastapi.testclient import TestClient
from pydantic import HttpUrl
from sqlalchemy.engine import make_url

from app.core.errors import StoreError
from app.main import create_app
from app.store.db import create_engine, ping
from tests.support.app_factory import make_settings

pytestmark = pytest.mark.integration


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL must point at the docker-compose.test.yml database")
    return url


def test_readyz_against_real_postgres(database_url: str) -> None:
    """The database-backed probes pass against the test Postgres; the providers point at a
    closed local port (no live call from the test suite), so their critical probes fail and
    the service is honestly not ready."""
    nowhere = HttpUrl("http://127.0.0.1:1/v1")
    settings = make_settings(database_url=database_url).model_copy(
        update={
            "model_api_base_url": nowhere,
            "safety_base_url": nowhere,
            "sidecar_base_url": nowhere,
        }
    )
    with TestClient(create_app(settings=settings)) as client:
        response = client.get("/readyz")
    checks = {
        check["name"]: (check["ok"], check["critical"]) for check in response.json()["checks"]
    }
    assert checks == {
        "database": (True, True),
        "schema": (True, True),  # the test database is at the newest migration
        "queue": (True, True),
        "model_api": (False, True),
        "safety": (False, True),
        "sidecar": (False, False),  # text replies still go out without the voice server
        "ffmpeg": (True, False),
    }
    assert response.status_code == 503


async def test_ping_raises_store_error_on_bad_credentials(database_url: str) -> None:
    wrong_credential = "definitely-wrong"
    wrong = make_url(database_url).set(password=wrong_credential)
    settings = make_settings(database_url=wrong.render_as_string(hide_password=False))
    engine = create_engine(settings)
    try:
        with pytest.raises(StoreError, match="database ping failed") as caught:
            await ping(engine)
        assert caught.value.__cause__ is not None
        assert wrong_credential not in str(caught.value)
    finally:
        await engine.dispose()
