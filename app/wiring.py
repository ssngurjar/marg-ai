"""Composition root: the only module that builds concrete adapters.

Everything else receives its dependencies. Later steps add fields (language model, transcriber,
WhatsApp sender, …) to `Container` and build them in `build_container`.
"""

from dataclasses import dataclass
from functools import partial

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.readiness import ReadinessProbe
from app.channels.whatsapp.client import WhatsAppConfig, WhatsAppSender
from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.core.identity import UserIdentity
from app.store.db import create_engine, create_session_factory, ping
from app.store.repositories.inbound import InboundStore


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    clock: Clock
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    readiness_probes: tuple[ReadinessProbe, ...]
    identity: UserIdentity
    whatsapp_sender: WhatsAppSender
    inbound_store: InboundStore


def build_container(settings: Settings) -> Container:
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    clock = SystemClock()
    whatsapp_config = WhatsAppConfig(
        graph_base_url=str(settings.whatsapp_graph_base_url),
        phone_number_id=settings.whatsapp_phone_number_id,
        access_token=settings.whatsapp_access_token,
        timeout_s=settings.timeout_whatsapp_s,
    )
    return Container(
        settings=settings,
        clock=clock,
        engine=engine,
        session_factory=session_factory,
        readiness_probes=(
            ReadinessProbe(name="database", critical=True, check=partial(ping, engine)),
        ),
        identity=UserIdentity(settings.user_hash_salt, settings.address_encryption_key),
        whatsapp_sender=WhatsAppSender(config=whatsapp_config, clock=clock),
        inbound_store=InboundStore(session_factory),
    )


async def close_container(container: Container) -> None:
    """Release what the container opened: HTTP connections and the database pool."""
    await container.whatsapp_sender.aclose()
    await container.engine.dispose()
