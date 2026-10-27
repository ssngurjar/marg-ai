"""WhatsAppSender: sending parts to WhatsApp through the Graph API (s03 §4.9, §4.10).

One HTTP attempt per call, with a timeout. Retries belong to the caller (the reply deliverer),
which uses each error's `retryable` flag. The sender never touches the database: audio and image
bytes are passed in.
"""

from dataclasses import dataclass

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from app.channels.whatsapp.graph_error_classifier import GraphErrorClassifier
from app.channels.whatsapp.graph_message_builder import GraphMessageBuilder
from app.channels.whatsapp.payloads import GraphMediaUploadResponse, GraphSendResponse
from app.constants.whatsapp import PROVIDER, VOICE_NOTE_MIME
from app.core.clock import Clock
from app.core.errors import ProviderResponseInvalid, ProviderTimeout, ProviderUnavailable
from app.core.logging import get_logger
from app.core.types import JsonValue
from app.domain.enums import Channel, PartKind
from app.domain.models.message import AudioClip, ImageClip
from app.domain.models.reply import OutboundPart
from app.providers.ports import ChannelAddress, DeliveryReceipt

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
        sent = _parse_response(GraphSendResponse, response)
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
        return _parse_response(GraphMediaUploadResponse, response).id

    async def _message_body(
        self, part: OutboundPart, audio: AudioClip | None, image: ImageClip | None
    ) -> dict[str, JsonValue]:
        match part.kind:
            case PartKind.TEXT:
                return GraphMessageBuilder.text_body(part)
            case PartKind.INTERACTIVE:
                return GraphMessageBuilder.interactive_body(part)
            case PartKind.AUDIO:
                clip = GraphMessageBuilder.require_voice_note(part, audio)
                media_id = await self.upload_media(clip.data, VOICE_NOTE_MIME, "reply.ogg")
                return {"type": "audio", "audio": {"id": media_id}}
            case PartKind.IMAGE:
                card = GraphMessageBuilder.require_image(part, image)
                extension = "png" if card.mime_type == "image/png" else "jpg"
                media_id = await self.upload_media(card.data, card.mime_type, f"card.{extension}")
                image_object: dict[str, JsonValue] = {"id": media_id}
                if part.text:
                    image_object["caption"] = part.text
                return {"type": "image", "image": image_object}
            case PartKind.TEMPLATE:
                return GraphMessageBuilder.template_body(part)

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
        error = GraphErrorClassifier.classify(response.status_code, response.content)
        logger.warning(
            "whatsapp_request_failed",
            endpoint=path.rsplit("/", maxsplit=1)[-1],
            http_status=response.status_code,
            error=type(error).__name__,
            retryable=error.retryable,
        )
        raise error


def _parse_response[ResponseModel: BaseModel](
    model: type[ResponseModel], response: httpx.Response
) -> ResponseModel:
    try:
        return model.model_validate_json(response.content)
    except ValidationError as exc:
        raise ProviderResponseInvalid(
            f"graph api returned an unexpected {model.__name__}", provider=PROVIDER
        ) from exc
