"""Identifiers and the base every domain model shares (contracts.md §2.1).

Models grow in stages (s04 decisions log, 2026-10-27): each field is added, complete, by the step
that builds what it describes, so nothing here is a placeholder for a later step.
"""

from typing import NewType
from uuid import UUID

from pydantic import BaseModel, ConfigDict

UserHash = NewType("UserHash", str)
"""64 lowercase hex chars: HMAC-SHA256(USER_HASH_SALT, "<channel>:<address>")."""

TurnId = NewType("TurnId", UUID)


class DomainModel(BaseModel):
    """Frozen; unknown fields are rejected."""

    model_config = ConfigDict(frozen=True, extra="forbid")
