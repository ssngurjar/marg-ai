"""FastAPI dependencies that read what the app factory put on `app.state`."""

from fastapi import Request

from app.api.readiness import ReadinessProbe
from app.core.config import Environment, Settings
from app.core.errors import ConfigError


def get_settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        raise ConfigError("app.state.settings is not set; build the app with create_app()")
    return settings


def get_environment(request: Request) -> Environment:
    return get_settings(request).environment


def get_readiness_probes(request: Request) -> tuple[ReadinessProbe, ...]:
    probes = request.app.state.readiness_probes
    if not isinstance(probes, tuple):
        raise ConfigError("app.state.readiness_probes is not set; build the app with create_app()")
    checked: list[ReadinessProbe] = []
    for probe in probes:
        if not isinstance(probe, ReadinessProbe):
            raise ConfigError(f"app.state.readiness_probes holds a {type(probe).__name__}")
        checked.append(probe)
    return tuple(checked)
