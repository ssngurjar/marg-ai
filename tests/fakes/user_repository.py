"""A UserRepository that records purge requests instead of touching a database."""

from datetime import timedelta

from app.domain.models.base import TurnId, UserHash
from app.store.repositories.user_repository import UserRepository


class MemoryUserRepository(UserRepository):
    def __init__(self, *, marked_turns: frozenset[TurnId] = frozenset()) -> None:
        self.marked_turns = set(marked_turns)
        self.purged_turns: list[TurnId] = []
        self.sweeps: list[timedelta] = []

    async def purge_if_delivered(self, turn_id: TurnId) -> bool:
        if turn_id in self.marked_turns:
            self.marked_turns.discard(turn_id)
            self.purged_turns.append(turn_id)
            return True
        return False

    async def sweep_purges(self, older_than: timedelta) -> int:
        self.sweeps.append(older_than)
        return 0

    async def purge_user(self, user_hash: UserHash) -> bool:
        return False
