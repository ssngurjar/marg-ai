"""TurnWaker: what an ingress needs from the turn dispatcher (s04 §4.3)."""

from typing import Protocol

from app.domain.models.base import UserHash


class TurnWaker(Protocol):
    """Start this user's turn soon."""

    def wake(self, user_hash: UserHash) -> None: ...
