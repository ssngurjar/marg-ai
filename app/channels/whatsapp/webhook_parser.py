"""WhatsAppWebhookParser: a verified webhook into typed messages and statuses (s03 §4.4).

No I/O here: identity hashing is in memory, and the route hands the result to the repository.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import ClassVar

from pydantic import SecretStr, ValidationError

from app.channels.whatsapp.parsed_webhook import (
    NotStored,
    ParsedMessage,
    ParsedWebhook,
    StatusUpdate,
)
from app.channels.whatsapp.payloads import (
    WaError,
    WaMessage,
    WaMessageEnvelope,
    WaMessagesChange,
    WaStatus,
    WaValue,
    WebhookBody,
)
from app.constants.whatsapp import NOT_STORED_MESSAGE_TYPES, WHATSAPP_OBJECT
from app.core.types import JsonValue
from app.core.user_identity import UserIdentity
from app.domain.enums import Channel, MessageKind, OutboxStatus
from app.domain.models.base import UserHash
from app.domain.models.message import InboundMessage, MediaRef


class WhatsAppWebhookParser:
    _STATUS_FROM_META: ClassVar[dict[str, OutboxStatus]] = {
        "sent": OutboxStatus.SENT,
        "delivered": OutboxStatus.DELIVERED,
        "read": OutboxStatus.READ,
        "played": OutboxStatus.READ,  # a voice note was played
        "failed": OutboxStatus.FAILED,
    }

    @staticmethod
    def parse(
        body: WebhookBody, own_phone_number_id: str, identity: UserIdentity, received_at: datetime
    ) -> ParsedWebhook:
        messages: list[ParsedMessage] = []
        statuses: list[StatusUpdate] = []
        account_errors: list[WaError] = []
        ignored = foreign = malformed = 0
        if body.object != WHATSAPP_OBJECT:
            return ParsedWebhook(
                messages=[], statuses=[], ignored=1, foreign_phone_number_id=0, malformed=0,
                account_errors=[],
            )  # fmt: skip
        for value in WhatsAppWebhookParser._message_changes(body):
            if value is None:
                ignored += 1
                continue
            if value.metadata.phone_number_id != own_phone_number_id:
                foreign += 1
                continue
            account_errors.extend(value.errors)
            for raw_message in value.messages:
                outcome = WhatsAppWebhookParser._parse_message(raw_message, identity, received_at)
                if outcome is None:
                    malformed += 1
                elif isinstance(outcome, NotStored):
                    ignored += 1
                else:
                    messages.append(outcome)
            for raw_status in value.statuses:
                status = WhatsAppWebhookParser._parse_status(raw_status)
                if status is None:
                    malformed += 1
                else:
                    statuses.append(status)
        return ParsedWebhook(
            messages=messages,
            statuses=statuses,
            ignored=ignored,
            foreign_phone_number_id=foreign,
            malformed=malformed,
            account_errors=account_errors,
        )

    @staticmethod
    def _message_changes(body: WebhookBody) -> Iterator[WaValue | None]:
        """The value of every change; None for changes that aren't the `messages` field."""
        for entry in body.entry:
            for change in entry.changes:
                yield change.value if isinstance(change, WaMessagesChange) else None

    @staticmethod
    def _parse_message(
        raw: dict[str, JsonValue], identity: UserIdentity, received_at: datetime
    ) -> ParsedMessage | NotStored | None:
        """The parsed message, NotStored for types we don't keep, or None if it's malformed."""
        try:
            envelope = WaMessageEnvelope.model_validate(raw)
            sent_at = datetime.fromtimestamp(int(envelope.timestamp), UTC)
        except (ValidationError, ValueError, OverflowError):
            return None
        if envelope.type in NOT_STORED_MESSAGE_TYPES:
            return NotStored(envelope.type)
        user_hash = UserHash(identity.user_hash(Channel.WHATSAPP, envelope.from_))
        try:
            message = WaMessage.model_validate(raw)
        except ValidationError:
            message = None
        inbound = WhatsAppWebhookParser._to_inbound(
            envelope, message, user_hash, sent_at, received_at
        )
        return ParsedMessage(
            inbound=inbound,
            wa_id=SecretStr(envelope.from_),
            raw_payload=WhatsAppWebhookParser.strip_message_payload(envelope, message),
        )

    @staticmethod
    def _to_inbound(
        envelope: WaMessageEnvelope,
        message: WaMessage | None,
        user_hash: UserHash,
        sent_at: datetime,
        received_at: datetime,
    ) -> InboundMessage:
        kind = MessageKind.UNSUPPORTED
        text: str | None = None
        media: MediaRef | None = None
        reply_id: str | None = None
        if message is not None:
            if message.type == "text" and message.text is not None:
                kind, text = MessageKind.TEXT, message.text.body
            elif message.type == "audio" and message.audio is not None:
                kind = MessageKind.AUDIO
                media = WhatsAppWebhookParser._media_ref(message.audio.id, message.audio.mime_type)
            elif message.type == "image" and message.image is not None:
                kind, text = MessageKind.IMAGE, message.image.caption
                media = WhatsAppWebhookParser._media_ref(message.image.id, message.image.mime_type)
            elif message.type == "interactive" and message.interactive is not None:
                choice = message.interactive.button_reply or message.interactive.list_reply
                if choice is not None:
                    kind, text, reply_id = MessageKind.INTERACTIVE, choice.title, choice.id
            elif message.type == "button" and message.button is not None:
                # A tap on a template's quick reply, e.g. the daily nudge (payload "jrn:today").
                kind, text, reply_id = (
                    MessageKind.INTERACTIVE,
                    message.button.text,
                    message.button.payload,
                )
        return InboundMessage(
            channel=Channel.WHATSAPP,
            external_id=envelope.id,
            user_hash=user_hash,
            kind=kind,
            text=text,
            media=media,
            interactive_reply_id=reply_id,
            provider_sent_at=sent_at,
            received_at=received_at,
        )

    @staticmethod
    def _media_ref(media_id: str, mime_type: str) -> MediaRef:
        return MediaRef(
            channel=Channel.WHATSAPP, provider_media_id=media_id, blob_id=None, mime_type=mime_type
        )

    @staticmethod
    def strip_message_payload(
        envelope: WaMessageEnvelope, message: WaMessage | None
    ) -> dict[str, JsonValue]:
        """Build raw_payload from an allowlist (s03 §4.7).

        Never copied: `from`, contacts, `context.from`, media URLs and hashes, image captions.
        An allowlist can't leak a field Meta adds later.
        """
        kept: dict[str, JsonValue] = {
            "id": envelope.id,
            "timestamp": envelope.timestamp,
            "type": envelope.type,
        }
        if message is None:
            return kept
        if message.text is not None:
            kept["text"] = {"body": message.text.body}
        if message.audio is not None:
            kept["audio"] = {
                "id": message.audio.id,
                "mime_type": message.audio.mime_type,
                "voice": message.audio.voice,
            }
        if message.image is not None:
            kept["image"] = {"id": message.image.id, "mime_type": message.image.mime_type}
        if message.interactive is not None:
            kept["interactive"] = WhatsAppWebhookParser._strip_interactive(message)
        if message.button is not None:
            kept["button"] = {"payload": message.button.payload, "text": message.button.text}
        if message.context is not None and message.context.id is not None:
            kept["context"] = {"id": message.context.id}
        if message.errors:
            kept["errors"] = [
                {"code": error.code, "title": error.title} for error in message.errors
            ]
        return kept

    @staticmethod
    def _strip_interactive(message: WaMessage) -> dict[str, JsonValue]:
        interactive = message.interactive
        if interactive is None:
            return {}
        stripped: dict[str, JsonValue] = {"type": interactive.type}
        if interactive.button_reply is not None:
            stripped["button_reply"] = {
                "id": interactive.button_reply.id,
                "title": interactive.button_reply.title,
            }
        if interactive.list_reply is not None:
            stripped["list_reply"] = {
                "id": interactive.list_reply.id,
                "title": interactive.list_reply.title,
            }
        return stripped

    @staticmethod
    def _parse_status(raw: dict[str, JsonValue]) -> StatusUpdate | None:
        try:
            status = WaStatus.model_validate(raw)
            at = datetime.fromtimestamp(int(status.timestamp), UTC)
        except (ValidationError, ValueError, OverflowError):
            return None
        first_error = status.errors[0] if status.errors else None
        return StatusUpdate(
            provider_message_id=status.id,
            status=WhatsAppWebhookParser._STATUS_FROM_META[status.status],
            at=at,
            error_code=first_error.code if first_error else None,
            error_title=first_error.title if first_error else None,
        )
