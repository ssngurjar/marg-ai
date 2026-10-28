"""App factory, used by `uvicorn app.main:create_app --factory` and by tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Final

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routers import dashboard, demo, health, whatsapp_webhook
from app.core.config import Settings, load_settings
from app.core.logging import configure_logging
from app.wiring import Container, build_container, close_container

STATIC: Final = Path(__file__).resolve().parent / "static"


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    """Build the FastAPI app.

    Settings come from the given container, the given settings, or the environment, in that
    order. A container passed in (tests) is used as-is and not closed by the app.
    """
    if container is not None:
        resolved_settings = container.settings
    elif settings is not None:
        resolved_settings = settings
    else:
        resolved_settings = load_settings()
    configure_logging(resolved_settings.log_level, environment=resolved_settings.environment)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active_container = container or build_container(resolved_settings)
        app.state.container = active_container
        app.state.settings = active_container.settings
        app.state.readiness_probes = active_container.readiness_probes
        app.state.identity = active_container.identity
        app.state.inbox_repository = active_container.inbox_repository
        app.state.outbox_repository = active_container.outbox_repository
        app.state.clock = active_container.clock
        app.state.turn_waker = active_container.turn_dispatcher
        app.state.web_demo = active_container.web_demo
        app.state.media_repository = active_container.voice_adapters.media
        app.state.user_repository = active_container.user_repository
        app.state.telemetry_pages = active_container.telemetry_pages
        await active_container.turn_dispatcher.start()
        try:
            yield
        finally:
            await active_container.turn_dispatcher.stop()
            if container is None:
                await close_container(active_container)

    is_prod = resolved_settings.environment == "prod"
    app = FastAPI(
        title="Marg.ai",
        lifespan=lifespan,
        docs_url=None if is_prod else "/docs",
        redoc_url=None,
        openapi_url=None if is_prod else "/openapi.json",
    )
    app.include_router(health.router)
    app.include_router(whatsapp_webhook.router)
    app.include_router(demo.router)
    app.include_router(dashboard.router)
    app.mount("/demo/static", StaticFiles(directory=STATIC / "demo"), name="demo-static")
    return app
