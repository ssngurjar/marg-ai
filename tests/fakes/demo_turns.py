"""FakeDemoTurns: the demo repository's turn reads, from a dictionary (no database)."""

from datetime import timedelta
from uuid import UUID

from app.core.errors import StoreError
from app.domain.models.base import UserHash
from app.store.repositories.demo_repository import DemoRepository, TurnView


class FakeDemoTurns(DemoRepository):
    """Turns by id with their owner; `latest` per visitor; `fail` makes every read raise."""

    def __init__(self) -> None:  # deliberately skips the real session factory
        self.owners: dict[UUID, UserHash] = {}
        self.views: dict[UUID, TurnView] = {}
        self.latest: dict[UserHash, TurnView] = {}
        self.owner_lookups: list[UUID] = []
        self.fail = False

    def add(self, owner: UserHash, view: TurnView) -> None:
        self.owners[view.turn_id] = owner
        self.views[view.turn_id] = view

    async def turn_owner(self, turn_id: UUID) -> UserHash | None:
        self._maybe_fail()
        self.owner_lookups.append(turn_id)
        return self.owners.get(turn_id)

    async def visitor_turn(self, user_hash: UserHash, turn_id: UUID) -> TurnView | None:
        self._maybe_fail()
        if self.owners.get(turn_id) != user_hash:
            return None
        return self.views.get(turn_id)

    async def latest_turn(self, user_hash: UserHash, within: timedelta) -> TurnView | None:
        self._maybe_fail()
        return self.latest.get(user_hash)

    def _maybe_fail(self) -> None:
        if self.fail:
            raise StoreError("could not read a demo turn: OperationalError")
