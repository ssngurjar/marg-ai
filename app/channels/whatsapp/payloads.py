"""Typed models of WhatsApp Cloud API webhooks and Graph API responses (s03 §5.2).

These are external models, so unlike the rest of the app they ignore unknown fields: Meta adds
fields without notice, and a new optional field must not make every webhook unparseable.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag

from app.core.types import JsonValue


class ExternalModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)


class WaMetadata(ExternalModel):
    display_phone_number: str
    phone_number_id: str


class WaContactProfile(ExternalModel):
    name: str | None = None


class WaContact(ExternalModel):
    wa_id: str
    profile: WaContactProfile | None = None


class WaText(ExternalModel):
    body: str


class WaAudio(ExternalModel):
    id: str
    mime_type: str
    sha256: str | None = None
    voice: bool | None = None


class WaImage(ExternalModel):
    id: str
    mime_type: str
    sha256: str | None = None
    caption: str | None = None


class WaButtonReply(ExternalModel):
    id: str
    title: str


class WaListReply(ExternalModel):
    id: str
    title: str
    description: str | None = None


class WaInteractive(ExternalModel):
    type: Literal["button_reply", "list_reply"]
    button_reply: WaButtonReply | None = None
    list_reply: WaListReply | None = None


class WaButton(ExternalModel):
    """A tap on a template's quick-reply button (e.g. the daily nudge)."""

    payload: str
    text: str


class WaContext(ExternalModel):
    id: str | None = None
    from_: str | None = Field(default=None, alias="from")


class WaErrorData(ExternalModel):
    details: str | None = None


class WaError(ExternalModel):
    code: int
    title: str | None = None
    message: str | None = None
    error_data: WaErrorData | None = None


class WaMessage(ExternalModel):
    from_: str = Field(alias="from")
    id: str
    timestamp: str
    type: str  # a str, not a Literal: unknown types must validate and become UNSUPPORTED
    text: WaText | None = None
    audio: WaAudio | None = None
    image: WaImage | None = None
    interactive: WaInteractive | None = None
    button: WaButton | None = None
    context: WaContext | None = None
    errors: list[WaError] = []


class WaStatus(ExternalModel):
    id: str
    status: Literal["sent", "delivered", "read", "played", "failed"]
    timestamp: str
    recipient_id: str
    errors: list[WaError] = []


class WaMessageEnvelope(ExternalModel):
    """The fields every message must have before we can store anything about it."""

    from_: str = Field(alias="from")
    id: str
    timestamp: str
    type: str = "unknown"


class WaValue(ExternalModel):
    """Messages and statuses are kept raw here and validated one by one, so a single malformed
    message can't make the whole batch unparseable (s03 §4.4)."""

    messaging_product: Literal["whatsapp"]
    metadata: WaMetadata
    contacts: list[WaContact] = []
    messages: list[dict[str, JsonValue]] = []
    statuses: list[dict[str, JsonValue]] = []
    errors: list[WaError] = []


class WaMessagesChange(ExternalModel):
    field: Literal["messages"]
    value: WaValue


class WaOtherChange(ExternalModel):
    """A change for another subscribed field (account_update, template status, …). Its value has
    a different shape and is not read; it is only counted as ignored (s03 §4.4)."""

    field: str
    value: JsonValue = None


def _change_kind(change: object) -> str:
    field = change.get("field") if isinstance(change, dict) else getattr(change, "field", None)
    return "messages" if field == "messages" else "other"


# Chosen by `field`, not by trying each model: a malformed `messages` change must fail
# validation, never be accepted as an ignorable "other" change.
type WaChange = Annotated[
    Annotated[WaMessagesChange, Tag("messages")] | Annotated[WaOtherChange, Tag("other")],
    Discriminator(_change_kind),
]


class WaEntry(ExternalModel):
    id: str
    changes: list[WaChange]


class WebhookBody(ExternalModel):
    object: str
    entry: list[WaEntry]


# --- Graph API responses ------------------------------------------------------------------


class GraphSentMessage(ExternalModel):
    id: str


class GraphSendResponse(ExternalModel):
    messages: list[GraphSentMessage] = Field(min_length=1)


class GraphMediaUploadResponse(ExternalModel):
    id: str


class GraphErrorDetail(ExternalModel):
    message: str | None = None
    type: str | None = None
    code: int | None = None
    error_subcode: int | None = None


class GraphErrorEnvelope(ExternalModel):
    error: GraphErrorDetail
