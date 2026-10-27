"""TurnContext builders for pipeline tests."""

from datetime import UTC, datetime
from uuid import uuid4

from app.domain.enums import Channel, ConversationState, MessageKind
from app.domain.models.base import TurnId, UserHash
from app.domain.models.message import InboundMessage, MediaRef
from app.domain.models.turn import TurnContext, UserProfile

NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
USER = UserHash("c" * 64)


def text_message(text: str) -> InboundMessage:
    return _message(MessageKind.TEXT, text=text)


def button_reply(reply_id: str, title: str = "Haan") -> InboundMessage:
    return _message(MessageKind.INTERACTIVE, text=title, interactive_reply_id=reply_id)


def media_message(kind: MessageKind, mime_type: str) -> InboundMessage:
    media = MediaRef(
        channel=Channel.WHATSAPP, provider_media_id="media-1", blob_id=None, mime_type=mime_type
    )
    return _message(kind, media=media)


def turn_context(*messages: InboundMessage) -> TurnContext:
    return TurnContext(
        turn_id=TurnId(uuid4()),
        profile=UserProfile(
            user_hash=USER,
            channel=Channel.WHATSAPP,
            state=ConversationState.ACTIVE,
            last_inbound_at=NOW,
        ),
        messages=list(messages),
        recent_exchanges=[],
        is_session_start=True,
    )


def _message(
    kind: MessageKind,
    *,
    text: str | None = None,
    media: MediaRef | None = None,
    interactive_reply_id: str | None = None,
) -> InboundMessage:
    return InboundMessage(
        channel=Channel.WHATSAPP,
        external_id=f"wamid.{uuid4().hex}",
        user_hash=USER,
        kind=kind,
        text=text,
        media=media,
        interactive_reply_id=interactive_reply_id,
        provider_sent_at=NOW,
        received_at=NOW,
    )
