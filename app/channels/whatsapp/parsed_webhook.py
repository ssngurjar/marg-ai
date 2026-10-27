"""What a verified WhatsApp webhook becomes after parsing (s03 §4.4 to §4.8). Data only."""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, SecretStr

from app.channels.whatsapp.payloads import WaError
from app.core.types import JsonValue
from app.domain.enums import OutboxStatus
from app.domain.models.message import InboundMessage


@dataclass(frozen=True, slots=True)
class NotStored:
    """A message type we deliberately don't store (a reaction, a number change)."""

    message_type: str


class StatusUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_message_id: str
    status: OutboxStatus
    at: datetime
    error_code: int | None
    error_title: str | None


class ParsedMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    inbound: InboundMessage
    wa_id: SecretStr  # for encrypting the address only; never logged
    raw_payload: dict[str, JsonValue]  # allowlisted: never holds the sender's number (§4.7)


class ParsedWebhook(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    messages: list[ParsedMessage]
    statuses: list[StatusUpdate]
    ignored: int  # reactions, system messages, other objects or fields
    foreign_phone_number_id: int  # changes addressed to a number that isn't ours
    malformed: int  # messages or statuses too broken to attribute to anyone
    account_errors: list[WaError]
