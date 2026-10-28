"""NotificationListener: Postgres `LISTEN` on one dedicated connection (s04 §4.11; s14 §4.6).

A notification means "look now", never "here is the work": each handler only sets an event or
wakes a stream, and the loops find the work with their own queries. When the connection drops,
the listener reconnects with backoff while the loops keep polling, so a lost notification costs
at most one poll interval. After every (re)connect each handler runs once, to catch up on what
was sent while nobody was listening.

The connection comes from its own engine without a pool (`create_listener_engine`): a `LISTEN`
must stay on one session, and must never go back to a pool other queries share.
"""

import asyncio
import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Final, Protocol, runtime_checkable

from asyncpg import exceptions as asyncpg_errors  # type: ignore[import-untyped]  # asyncpg ships no type information; only its exception classes are used here
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.errors import StoreError
from app.core.logging import get_logger

type NotificationHandler = Callable[[str], None]
"""Called with the notification's payload (often empty), on the event loop. Must not block."""

type _DriverCallback = Callable[[object, int, str, str], None]

LISTENER_ERRORS: Final = (
    SQLAlchemyError,
    OSError,
    StoreError,
    asyncpg_errors.InterfaceError,
    asyncpg_errors.PostgresError,
)

logger = get_logger(__name__)


@runtime_checkable
class _ListeningConnection(Protocol):
    """The part of asyncpg's connection used here (the driver ships no type information)."""

    async def add_listener(self, channel: str, callback: _DriverCallback) -> None: ...


@dataclass(frozen=True, slots=True)
class ListenerSettings:
    health_check_every: timedelta  # a SELECT 1 that notices a silently dropped connection
    reconnect_first: timedelta = timedelta(milliseconds=500)
    reconnect_cap: timedelta = timedelta(seconds=30)


class NotificationListener:
    def __init__(
        self,
        engine: AsyncEngine,
        handlers: Mapping[str, NotificationHandler],
        settings: ListenerSettings,
        rng: random.Random | None = None,
    ) -> None:
        self._engine = engine
        self._handlers = dict(handlers)
        self._settings = settings
        self._rng = rng or random.Random()  # noqa: S311  # reconnect jitter, not security
        self.connected = asyncio.Event()  # set while listening (tests and readiness)

    async def run(self, stop: asyncio.Event) -> None:
        """Listen until `stop` is set, reconnecting with backoff after every failure."""
        delay = self._settings.reconnect_first
        while not stop.is_set():
            try:
                await self._listen(stop)
            except LISTENER_ERRORS as exc:
                self.connected.clear()
                logger.warning("listener_disconnected", error=type(exc).__name__, exc_info=exc)
            else:
                return
            jitter = 0.5 + self._rng.random()  # between half and one and a half times the delay
            await _wait(stop, delay * jitter)
            delay = min(delay * 2, self._settings.reconnect_cap)

    async def _listen(self, stop: asyncio.Event) -> None:
        async with self._engine.connect() as connection:
            raw = await connection.get_raw_connection()
            driver = raw.driver_connection
            if not isinstance(driver, _ListeningConnection):
                raise StoreError("the database driver can't LISTEN (asyncpg expected)")
            for channel in self._handlers:
                await driver.add_listener(channel, self._on_notification)
            self.connected.set()
            logger.info("listener_connected", channels=sorted(self._handlers))
            for handler in self._handlers.values():
                handler("")  # catch up on anything sent while nobody was listening
            while not await _wait(stop, self._settings.health_check_every):
                await connection.execute(text("SELECT 1"))
        self.connected.clear()

    def _on_notification(self, _connection: object, _pid: int, channel: str, payload: str) -> None:
        handler = self._handlers.get(channel)
        if handler is not None:
            handler(payload)


async def _wait(stop: asyncio.Event, longest: timedelta) -> bool:
    """Wait for `stop`, at most `longest`. True when it was set."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=longest.total_seconds())
    except TimeoutError:
        return False
    return True
