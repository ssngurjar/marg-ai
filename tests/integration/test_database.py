"""Needs `make test-db-up` (docker-compose.test.yml) and DATABASE_URL pointing at it."""

import os

import pytest
from fastapi.testclient import TestClient
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
    settings = make_settings(database_url=database_url)
    with TestClient(create_app(settings=settings)) as client:
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["checks"] == [
        {"name": "database", "ok": True, "detail": None, "critical": True},
        {"name": "ffmpeg", "ok": True, "detail": None, "critical": False},  # voice (s06)
    ]


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
