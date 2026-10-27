"""FastAPI dependencies that read what the app factory put on `app.state`."""

from typing import Protocol, cast

from fastapi import Request

from app.api.readiness import ReadinessProbe
from app.core.clock import Clock
from app.core.config import Environment, Settings
from app.core.errors import ConfigError
from app.core.user_identity import UserIdentity
from app.domain.models.base import UserHash
from app.store.repositories.inbox_repository import InboxRepository
from app.store.repositories.outbox_repository import OutboxRepository


class TurnWaker(Protocol):
    """What the webhook needs from the turn dispatcher: start this user's turn soon."""

    def wake(self, user_hash: UserHash) -> None: ...


def get_turn_waker(request: Request) -> TurnWaker:
    waker = request.app.state.turn_waker
    if not callable(getattr(waker, "wake", None)):
        raise ConfigError("app.state.turn_waker is not set; build the app with create_app()")
    return cast(TurnWaker, waker)


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


def get_identity(request: Request) -> UserIdentity:
    identity = request.app.state.identity
    if not isinstance(identity, UserIdentity):
        raise ConfigError("app.state.identity is not set; build the app with create_app()")
    return identity


def get_inbox_repository(request: Request) -> InboxRepository:
    store = request.app.state.inbox_repository
    if not isinstance(store, InboxRepository):
        raise ConfigError("app.state.inbox_repository is not set; build the app with create_app()")
    return store


def get_outbox_repository(request: Request) -> OutboxRepository:
    store = request.app.state.outbox_repository
    if not isinstance(store, OutboxRepository):
        raise ConfigError("app.state.outbox_repository is not set; build the app with create_app()")
    return store


def get_clock(request: Request) -> Clock:
    clock = request.app.state.clock
    if not callable(getattr(clock, "now", None)):
        raise ConfigError("app.state.clock is not set; build the app with create_app()")
    return cast(Clock, clock)
