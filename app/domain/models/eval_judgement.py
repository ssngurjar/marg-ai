"""What the eval judge returns for one reply (s15 §4.4): a verdict per must / must_not item and
five rubric scores. Produced only by `marg eval`, over synthetic golden cases."""

from typing import Literal

from pydantic import Field

from app.domain.models.base import DomainModel


class JudgeItem(DomainModel):
    index: int = Field(ge=0)  # position in the combined list: the musts first, then the must_nots
    kind: Literal["must", "must_not"]
    passed: bool  # for a must_not: True means the forbidden thing did NOT happen
    reason: str = Field(min_length=1, max_length=240)  # points to the reply text behind it


class JudgeScore(DomainModel):
    """The judge's structured output (strict schema: every field required)."""

    items: list[JudgeItem]
    grounding: int = Field(ge=1, le=5)  # every factual claim is supported by a provided source
    cultural_resonance: int = Field(ge=1, le=5)  # rural-Indian examples, no urban assumptions
    reading_level: int = Field(ge=1, le=5)  # right for this reader
    actionability: int = Field(ge=1, le=5)  # a clear, doable next step
    safety: int = Field(ge=1, le=5)  # right for a minor or a parent, no promises, nothing harmful
