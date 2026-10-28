"""What a parent's photo of the child's work tells us: counts only, never the image (s10b §4.14)."""

from pydantic import Field

from app.domain.models.base import DomainModel


class ObjectCount(DomainModel):
    """How many of one thing SAM 3.1 found, e.g. 7 of "leaf"."""

    phrase: str = Field(min_length=1, max_length=40)
    count: int = Field(ge=0)


class PhotoFindings(DomainModel):
    """The counts for the open activity's phrases. Empty when the activity has nothing to count
    (the photo was still checked and welcomed)."""

    counts: list[ObjectCount]
