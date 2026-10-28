"""What a student's own words say about where they're heading (s13 §4.3). Never a label."""

from datetime import datetime
from typing import Final, Literal

from pydantic import Field, model_validator

from app.domain.enums import AspirationField, ConstraintKind, Sentiment
from app.domain.models.base import DomainModel, TurnId
from app.domain.models.learner import LearnerId

NAMES_A_FIELD: Final = 2
"""Specificity 2 is the first level that names a field."""


class AspirationSignals(DomainModel):
    """The extraction's output (strict schema) and the persisted shape. Specificity 0-4: no career
    content, curiosity, a field, a role or path, an action taken or committed to."""

    fields: list[AspirationField] = Field(max_length=3)
    specificity: int = Field(ge=0, le=4)
    constraints: list[ConstraintKind] = Field(max_length=3)
    sentiment: Sentiment

    @model_validator(mode="after")
    def _consistent(self) -> "AspirationSignals":
        if len(set(self.fields)) != len(self.fields) or len(set(self.constraints)) != len(
            self.constraints
        ):
            raise ValueError("fields and constraints must not repeat")
        if self.specificity == 0 and self.fields:
            raise ValueError("specificity 0 has no fields")
        if self.specificity >= NAMES_A_FIELD and not self.fields:
            raise ValueError("specificity 2 or more names at least one field")
        return self


class ExtractAspiration(DomainModel):
    """Post-turn task (s13 §4.2): aspiration signals from a student's mentor or roadmap turn."""

    kind: Literal["extract_aspiration"] = "extract_aspiration"
    turn_id: TurnId
    learner_id: LearnerId  # the student's own `self` learner
    user_text: str
    previous_exchange: str  # the turn before, so "uske liye" resolves; "" for none
    grade: int | None
    at: datetime
