"""What we send back (contracts.md §2.6). S3 adds the parts the WhatsApp sender needs."""

from uuid import UUID

from pydantic import Field, HttpUrl

from app.domain.enums import Language, PartKind
from app.domain.models import DomainModel


class ReplyButton(DomainModel):
    """A WhatsApp reply button. At most 3 per message."""

    id: str = Field(min_length=1, max_length=256)  # namespaced: "onb:", "jrn:", "kid:", …
    title: str = Field(min_length=1, max_length=20)  # WhatsApp's title limit


class TemplateRef(DomainModel):
    """A Meta-approved template, for business-initiated messages (parent nudges)."""

    name: str
    language_code: str  # e.g. "hi", "en"
    button_payloads: list[str]  # quick-reply payloads, e.g. ["jrn:today"]


class OutboundPart(DomainModel):
    """One outbound message within a reply, delivered in `part_no` order."""

    part_no: int = Field(ge=0)
    kind: PartKind
    text: str | None  # the body; for IMAGE, the caption
    audio_blob_id: UUID | None
    image_blob_id: UUID | None
    buttons: list[ReplyButton]
    template: TemplateRef | None


class Citation(DomainModel):
    title: str
    source_url: HttpUrl
    chunk_id: UUID


class LocalisedReply(DomainModel):
    """A reply in the user's register: what `safety_out` checks and the gate seals."""

    text: str  # for the screen
    spoken_text: str  # for TTS: no URLs, markdown, emoji or markers
    reply_register: Language  # contracts: `register`, renamed: pydantic reserves the name
    citations: list[Citation]
    buttons: list[ReplyButton] = Field(max_length=3)
