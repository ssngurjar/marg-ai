"""Protocols the pipeline and layers depend on (contracts.md §3).

S1 declares only `Clock`; later steps add the provider ports.
"""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """Source of the current time: aware UTC."""

    def now(self) -> datetime: ...
