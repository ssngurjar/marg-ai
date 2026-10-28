"""TurnEventStream: one visitor's live trace as Server-Sent Events (s14 §4.4).

On (re)connect the stream replays the visitor's latest turn if it started in the last two
minutes, marked `replay`, so a page that reconnects mid-turn catches up. After that, every
time the hub queues one of their turns, the stream reads that turn and sends it whole, as a
`turn` event: the page re-renders it, so a repeated or replayed event is harmless and no
de-duplication is needed. A `: ping` comment every 15 s keeps proxies from closing an idle
stream. The stream ends after DEMO_SSE_MAX_S (the browser reconnects), when its queue
overflowed, or with an `error` event when the database can't be read.
"""

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import timedelta
from typing import Final
from uuid import UUID

from app.api.demo_view_serializer import DemoViewSerializer
from app.api.turn_progress_hub import LATEST, Subscription, TurnProgressHub
from app.core.errors import StoreError
from app.core.logging import get_logger
from app.store.repositories.demo_repository import DemoRepository, TurnView

RECONNECT_AFTER_MS: Final = 2000
PING: Final = ": ping\n\n"

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class StreamSettings:
    max_age: timedelta  # DEMO_SSE_MAX_S
    heartbeat: timedelta  # 15 s
    replay_window: timedelta  # 2 min: the latest turn replayed on connect


class TurnEventStream:
    def __init__(
        self, hub: TurnProgressHub, demo: DemoRepository, settings: StreamSettings
    ) -> None:
        self._hub = hub
        self._demo = demo
        self._settings = settings

    async def events(self, subscription: Subscription) -> AsyncGenerator[str]:
        """The stream's text. Always closes the subscription, however the stream ends."""
        loop = asyncio.get_running_loop()
        closes_at = loop.time() + self._settings.max_age.total_seconds()
        try:
            yield f"retry: {RECONNECT_AFTER_MS}\n\n"
            latest = await self._latest(subscription)
            if latest is not None:
                yield _turn_event(latest, replay=True)
            while (remaining := closes_at - loop.time()) > 0 and not subscription.overflowed:
                wait = min(self._settings.heartbeat.total_seconds(), remaining)
                try:
                    first = await asyncio.wait_for(subscription.queue.get(), timeout=wait)
                except TimeoutError:
                    if closes_at - loop.time() > 0:  # idle, not over: keep proxies from closing it
                        yield PING
                    continue
                for queued in _drain(subscription, first):
                    view = (
                        await self._latest(subscription)
                        if queued is LATEST
                        else await self._demo.visitor_turn(subscription.user_hash, queued)
                    )
                    if view is not None:
                        yield _turn_event(view, replay=False)
        except StoreError as exc:
            logger.warning("turn_stream_store_error", exc_info=exc)
            yield _event("error", {"error": "server_busy"})
        finally:
            self._hub.close(subscription)

    async def _latest(self, subscription: Subscription) -> TurnView | None:
        return await self._demo.latest_turn(subscription.user_hash, self._settings.replay_window)


def _drain(subscription: Subscription, first: UUID | None) -> list[UUID | None]:
    """The first queued item plus everything queued behind it, each once, in order: a burst of
    step notifications for one turn becomes one read."""
    pending: list[UUID | None] = [first]
    while not subscription.queue.empty():
        queued = subscription.queue.get_nowait()
        if queued not in pending:
            pending.append(queued)
    return pending


def _turn_event(view: TurnView, *, replay: bool) -> str:
    return _event("turn", {**DemoViewSerializer.turn(view), "replay": replay})


def _event(name: str, data: dict[str, object]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
