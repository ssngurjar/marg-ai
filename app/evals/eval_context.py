"""EvalContext: which case's turn is running, for the recorders shared across cases (s15 §4.2).

Cases run concurrently through one pipeline. The runner sets the key before each turn; asyncio
tasks the turn starts inherit it, so a recorder files what it was given under the right turn.
"""

from contextvars import ContextVar
from typing import ClassVar


class EvalContext:
    _CURRENT: ClassVar[ContextVar[str]] = ContextVar("eval_turn_key", default="")

    @staticmethod
    def set(turn_key: str) -> None:
        EvalContext._CURRENT.set(turn_key)

    @staticmethod
    def current() -> str:
        """ "" outside an eval turn."""
        return EvalContext._CURRENT.get()
