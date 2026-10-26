"""Composition root: the only module that builds concrete adapters.

Everything else receives its dependencies. Later steps add fields (language model, transcriber,
WhatsApp sender, …) to `Container` and build them in `build_container`.
"""

from dataclasses import dataclass
from functools import partial

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.readiness import ReadinessProbe
from app.core.clock import SystemClock
from app.core.config import Settings
from app.providers.ports import Clock
from app.store.db import create_engine, create_session_factory, ping


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    clock: Clock
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    readiness_probes: tuple[ReadinessProbe, ...]


def build_container(settings: Settings) -> Container:
    engine = create_engine(settings)
    return Container(
        settings=settings,
        clock=SystemClock(),
        engine=engine,
        session_factory=create_session_factory(engine),
        readiness_probes=(
            ReadinessProbe(name="database", critical=True, check=partial(ping, engine)),
        ),
    )


async def close_container(container: Container) -> None:
    """Release what the container opened: the database connection pool."""
    await container.engine.dispose()
