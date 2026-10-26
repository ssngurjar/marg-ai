"""App factory, used by `uvicorn app.main:create_app --factory` and by tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health
from app.core.config import Settings, load_settings
from app.core.logging import configure_logging
from app.wiring import Container, build_container, close_container


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
        try:
            yield
        finally:
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
    return app
