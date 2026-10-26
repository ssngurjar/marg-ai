"""Sending to WhatsApp through the Graph API (s03 §4.9, §4.10).

One HTTP attempt per call, with a timeout. Retries belong to the caller (the outbox, from S4),
which uses each error's `retryable` flag. The sender never touches the database: audio and image
bytes are passed in.
"""

from dataclasses import dataclass
from typing import Final

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from app.channels.whatsapp.payloads import (
    GraphErrorEnvelope,
    GraphMediaUploadResponse,
    GraphSendResponse,
)
from app.core.clock import Clock
from app.core.errors import (
    ProviderError,
    ProviderRateLimited,
    ProviderRejected,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.core.logging import get_logger
from app.core.types import JsonValue
from app.domain.enums import Channel, PartKind
from app.domain.models import AudioClip, ImageClip
from app.domain.replies import OutboundPart
from app.providers.ports import ChannelAddress, DeliveryReceipt

PROVIDER: Final = "whatsapp"
MAX_TEXT_CHARS: Final = 4096
MAX_INTERACTIVE_BODY_CHARS: Final = 1024
MAX_BUTTONS: Final = 3
MAX_CAPTION_CHARS: Final = 1024
MAX_AUDIO_BYTES: Final = 16 * 1024 * 1024
MAX_IMAGE_BYTES: Final = 5 * 1024 * 1024
VOICE_NOTE_MIME: Final = "audio/ogg; codecs=opus"
IMAGE_MIMES: Final = frozenset({"image/jpeg", "image/png"})

RATE_LIMIT_CODES: Final = frozenset({4, 80007, 130429, 131056})
TRANSIENT_CODES: Final = frozenset({131000, 131016})

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WhatsAppConfig:
    graph_base_url: str  # pinned API version, e.g. https://graph.facebook.com/v26.0
    phone_number_id: str
    access_token: SecretStr
    timeout_s: float


class WhatsAppSender:
    """Implements ChannelSender for WhatsApp."""

    channel: Channel = Channel.WHATSAPP

    def __init__(
        self, *, config: WhatsAppConfig, clock: Clock, http: httpx.AsyncClient | None = None
    ) -> None:
        """`http` is for tests; normally the sender creates and owns its own client."""
        self._http = http if http is not None else httpx.AsyncClient()
        self._base_url = config.graph_base_url.rstrip("/")
        self._phone_number_id = config.phone_number_id
        self._access_token = config.access_token
        self._timeout_s = config.timeout_s
        self._clock = clock

    async def send(
        self,
        part: OutboundPart,
        recipient: ChannelAddress,
        audio: AudioClip | None = None,
        image: ImageClip | None = None,
    ) -> DeliveryReceipt:
        """Send one part. Raises ValueError for a malformed part (a bug upstream; nothing is
        truncated), or a ProviderError subclass from the Graph API."""
        if recipient.channel is not Channel.WHATSAPP:
            raise ValueError(f"WhatsAppSender can't send to a {recipient.channel} address")
        message = await self._message_body(part, audio, image)
        body: dict[str, JsonValue] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient.address.get_secret_value(),
            **message,
        }
        response = await self._post_json(f"/{self._phone_number_id}/messages", body)
        sent = _parse(GraphSendResponse, response)
        return DeliveryReceipt(provider_message_id=sent.messages[0].id, sent_at=self._clock.now())

    async def aclose(self) -> None:
        """Close the HTTP connections (called when the app shuts down)."""
        await self._http.aclose()

    async def acknowledge(self, external_id: str) -> None:
        """Mark the user's message read and show "typing…" (gone when we reply, or after 25 s)."""
        body: dict[str, JsonValue] = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": external_id,
            "typing_indicator": {"type": "text"},
        }
        await self._post_json(f"/{self._phone_number_id}/messages", body)

    async def upload_media(self, data: bytes, mime_type: str, filename: str) -> str:
        """Upload bytes to WhatsApp's media store; returns the media id to send."""
        response = await self._request(
            "POST",
            f"/{self._phone_number_id}/media",
            files={"file": (filename, data, mime_type)},
            data={"messaging_product": "whatsapp", "type": mime_type},
        )
        return _parse(GraphMediaUploadResponse, response).id

    async def _message_body(
        self, part: OutboundPart, audio: AudioClip | None, image: ImageClip | None
    ) -> dict[str, JsonValue]:
        match part.kind:
            case PartKind.TEXT:
                return text_body(part)
            case PartKind.INTERACTIVE:
                return interactive_body(part)
            case PartKind.AUDIO:
                clip = require_voice_note(part, audio)
                media_id = await self.upload_media(clip.data, VOICE_NOTE_MIME, "reply.ogg")
                return {"type": "audio", "audio": {"id": media_id}}
            case PartKind.IMAGE:
                card = require_image(part, image)
                extension = "png" if card.mime_type == "image/png" else "jpg"
                media_id = await self.upload_media(card.data, card.mime_type, f"card.{extension}")
                image_object: dict[str, JsonValue] = {"id": media_id}
                if part.text:
                    image_object["caption"] = part.text
                return {"type": "image", "image": image_object}
            case PartKind.TEMPLATE:
                return template_body(part)

    async def _post_json(self, path: str, body: dict[str, JsonValue]) -> httpx.Response:
        return await self._request("POST", path, json=body)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, JsonValue] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        data: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._http.request(
                method,
                f"{self._base_url}{path}",
                json=json,
                files=files,
                data=data,
                headers={"Authorization": f"Bearer {self._access_token.get_secret_value()}"},
                timeout=self._timeout_s,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(
                f"graph api {path.rsplit('/', maxsplit=1)[-1]} timed out", provider=PROVIDER
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(
                f"graph api {path.rsplit('/', maxsplit=1)[-1]} unreachable: {type(exc).__name__}",
                provider=PROVIDER,
            ) from exc
        if response.is_success:
            return response
        error = classify_graph_error(response.status_code, response.content)
        logger.warning(
            "whatsapp_request_failed",
            endpoint=path.rsplit("/", maxsplit=1)[-1],
            http_status=response.status_code,
            error=type(error).__name__,
            retryable=error.retryable,
        )
        raise error


# --- message bodies (pure, so they can be tested without HTTP) ------------------------------


def text_body(part: OutboundPart) -> dict[str, JsonValue]:
    body = part.text or ""
    if not 1 <= len(body) <= MAX_TEXT_CHARS:
        raise ValueError(f"text part must be 1..{MAX_TEXT_CHARS} chars, got {len(body)}")
    # No link previews: a preview is content in a child's chat that we didn't check.
    return {"type": "text", "text": {"body": body, "preview_url": False}}


def interactive_body(part: OutboundPart) -> dict[str, JsonValue]:
    body = part.text or ""
    if not 1 <= len(body) <= MAX_INTERACTIVE_BODY_CHARS:
        raise ValueError(f"interactive body must be 1..{MAX_INTERACTIVE_BODY_CHARS} chars")
    if not 1 <= len(part.buttons) <= MAX_BUTTONS:
        raise ValueError(
            f"interactive part needs 1..{MAX_BUTTONS} buttons, got {len(part.buttons)}"
        )
    buttons: list[JsonValue] = [
        {"type": "reply", "reply": {"id": button.id, "title": button.title}}
        for button in part.buttons
    ]
    return {
        "type": "interactive",
        "interactive": {"type": "button", "body": {"text": body}, "action": {"buttons": buttons}},
    }


def template_body(part: OutboundPart) -> dict[str, JsonValue]:
    if part.template is None:
        raise ValueError("template part has no template")
    if part.text is not None or part.audio_blob_id is not None or part.image_blob_id is not None:
        raise ValueError("template part must not carry text, audio or an image")
    if len(part.template.button_payloads) > MAX_BUTTONS:
        raise ValueError(f"a template has at most {MAX_BUTTONS} quick-reply buttons")
    components: list[JsonValue] = [
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": str(index),
            "parameters": [{"type": "payload", "payload": payload}],
        }
        for index, payload in enumerate(part.template.button_payloads)
    ]
    template: dict[str, JsonValue] = {
        "name": part.template.name,
        "language": {"code": part.template.language_code},
    }
    if components:
        template["components"] = components
    return {"type": "template", "template": template}


def require_voice_note(part: OutboundPart, audio: AudioClip | None) -> AudioClip:
    if part.audio_blob_id is None or audio is None:
        raise ValueError("audio part needs audio_blob_id and the clip's bytes")
    if audio.mime_type != VOICE_NOTE_MIME:
        raise ValueError(
            f"WhatsApp voice notes must be {VOICE_NOTE_MIME!r}, got {audio.mime_type!r}"
        )
    if not 0 < len(audio.data) <= MAX_AUDIO_BYTES:
        raise ValueError(f"voice note must be 1..{MAX_AUDIO_BYTES} bytes")
    return audio


def require_image(part: OutboundPart, image: ImageClip | None) -> ImageClip:
    if part.image_blob_id is None or image is None:
        raise ValueError("image part needs image_blob_id and the image's bytes")
    if image.mime_type not in IMAGE_MIMES:
        raise ValueError(f"WhatsApp images must be one of {sorted(IMAGE_MIMES)}")
    if not 0 < len(image.data) <= MAX_IMAGE_BYTES:
        raise ValueError(f"image must be 1..{MAX_IMAGE_BYTES} bytes")
    if part.text is not None and len(part.text) > MAX_CAPTION_CHARS:
        raise ValueError(f"caption must be at most {MAX_CAPTION_CHARS} chars, got {len(part.text)}")
    return image


# --- errors -----------------------------------------------------------------------------------


def classify_graph_error(status_code: int, body: bytes) -> ProviderError:
    """Map a failed Graph API response to our error types, by Meta's error code (s03 §4.10).

    Codes verified against Meta's error-code reference on 2026-10-27.
    """
    code: int | None = None
    try:
        code = GraphErrorEnvelope.model_validate_json(body).error.code
    except ValidationError:
        code = None
    label = f"graph api error {code}" if code is not None else f"graph api http {status_code}"
    if code in RATE_LIMIT_CODES or status_code == httpx.codes.TOO_MANY_REQUESTS:
        return ProviderRateLimited(label, provider=PROVIDER, retry_after=None)
    if code in TRANSIENT_CODES or status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
        return ProviderUnavailable(label, provider=PROVIDER)
    return ProviderRejected(label, provider=PROVIDER)


def _parse[ResponseModel: BaseModel](
    model: type[ResponseModel], response: httpx.Response
) -> ResponseModel:
    try:
        return model.model_validate_json(response.content)
    except ValidationError as exc:
        raise ProviderResponseInvalid(
            f"graph api returned an unexpected {model.__name__}", provider=PROVIDER
        ) from exc
