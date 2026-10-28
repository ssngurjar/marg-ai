"""TurnWaker: what an ingress needs from the worker (s04 §4.3): look for this user's turn now."""

from typing import Protocol

from app.domain.models.base import UserHash


class TurnWaker(Protocol):
    """Start this user's turn soon."""

    def wake(self, user_hash: UserHash) -> None: ...
