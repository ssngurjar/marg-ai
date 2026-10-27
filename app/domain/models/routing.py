"""Where a turn goes (contracts §2.5)."""

from pydantic import Field

from app.domain.enums import Mode, Route
from app.domain.models.base import DomainModel


class RouteDecision(DomainModel):
    route: Route
    mode_switch: Mode | None
    reason: str = Field(max_length=120)  # fixed vocabulary; never user text
