"""NotificationListener against real Postgres: wakes on NOTIFY, reconnects after a drop (s04 §4.11).

Needs `make test-db-up` and migrations applied (`make test-int` does both).
"""

import asyncio
import os
import random
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.store.db import create_engine, create_listener_engine
from app.store.notification_listener import ListenerSettings, NotificationListener
from tests.support.app_factory import make_settings

pytestmark = pytest.mark.integration

QUICK = ListenerSettings(
    health_check_every=timedelta(milliseconds=100),
    reconnect_first=timedelta(milliseconds=50),
    reconnect_cap=timedelta(milliseconds=200),
)


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL must point at the docker-compose.test.yml database")
    return url


@pytest.fixture
async def engines(database_url: str) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    engine = create_engine(make_settings(database_url=database_url))
    listen_engine = create_listener_engine(SecretStr(database_url))
    yield engine, listen_engine
    await listen_engine.dispose()
    await engine.dispose()


async def notify(engine: AsyncEngine, channel: str, payload: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("SELECT pg_notify(:c, :p)"), {"c": channel, "p": payload})


async def test_each_channel_reaches_only_its_own_handler(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    engine, listen_engine = engines
    heard: dict[str, list[str]] = {"inbox_new": [], "outbox_new": []}
    got_outbox = asyncio.Event()

    def on_outbox(payload: str) -> None:
        heard["outbox_new"].append(payload)
        if payload:
            got_outbox.set()

    listener = NotificationListener(
        listen_engine, {"inbox_new": heard["inbox_new"].append, "outbox_new": on_outbox}, QUICK
    )
    stop = asyncio.Event()
    running = asyncio.create_task(listener.run(stop))
    await asyncio.wait_for(listener.connected.wait(), timeout=5)
    await notify(engine, "outbox_new", "turn-1")
    await notify(engine, "some_other_channel", "ignored")
    await asyncio.wait_for(got_outbox.wait(), timeout=5)
    stop.set()
    await asyncio.wait_for(running, timeout=5)
    assert heard == {"inbox_new": [""], "outbox_new": ["", "turn-1"]}  # "" = the catch-up call


async def test_a_dropped_connection_is_reopened_and_catches_up(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    engine, listen_engine = engines
    wakes: list[str] = []
    woken = asyncio.Event()

    def on_inbox(payload: str) -> None:
        wakes.append(payload)
        woken.set()

    listener = NotificationListener(
        listen_engine,
        {"inbox_new": on_inbox},
        QUICK,
        rng=random.Random(1),  # noqa: S311  # test jitter
    )
    stop = asyncio.Event()
    running = asyncio.create_task(listener.run(stop))
    await asyncio.wait_for(listener.connected.wait(), timeout=5)
    woken.clear()
    async with engine.begin() as connection:  # the server drops every other session
        await connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
        )
    await asyncio.wait_for(woken.wait(), timeout=5)  # reconnected: the catch-up call
    woken.clear()
    await notify(engine, "inbox_new", "after-reconnect")
    await asyncio.wait_for(woken.wait(), timeout=5)
    stop.set()
    await asyncio.wait_for(running, timeout=5)
    assert wakes[-1] == "after-reconnect"
    assert wakes.count("") >= 2  # the first connect and the reconnect
