import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
import respx
from pydantic import SecretStr, ValidationError

from app.channels.whatsapp.graph_error_classifier import GraphErrorClassifier
from app.channels.whatsapp.whatsapp_sender import WhatsAppConfig, WhatsAppSender
from app.core.errors import (
    ProviderRateLimited,
    ProviderRejected,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.domain.enums import Channel, PartKind
from app.domain.models.message import AudioClip, ImageClip
from app.domain.models.reply import OutboundPart, ReplyButton, TemplateRef
from app.providers.ports import ChannelAddress
from tests.fakes.clock import FixedClock

pytestmark = pytest.mark.unit

BASE = "https://graph.facebook.com/v26.0"
PHONE_ID = "100000000000001"
MESSAGES_URL = f"{BASE}/{PHONE_ID}/messages"
MEDIA_URL = f"{BASE}/{PHONE_ID}/media"
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
RECIPIENT = ChannelAddress(channel=Channel.WHATSAPP, address=SecretStr("919000000001"))
SENT = {
    "messaging_product": "whatsapp",
    "messages": [{"id": "wamid.OUT1", "message_status": "accepted"}],
}


@pytest.fixture
async def sender() -> AsyncIterator[WhatsAppSender]:
    client = httpx.AsyncClient()
    config = WhatsAppConfig(BASE, PHONE_ID, SecretStr("token-for-tests"), timeout_s=5.0)
    yield WhatsAppSender(config=config, clock=FixedClock(NOW), http=client)
    await client.aclose()


def part(kind: PartKind, **fields: object) -> OutboundPart:
    values: dict[str, object] = {
        "part_no": 0, "kind": kind, "text": None, "audio_blob_id": None,
        "image_blob_id": None, "buttons": [], "template": None,
    }  # fmt: skip
    values.update(fields)
    return OutboundPart.model_validate(values)


def sent_json(route: respx.Route, call: int = 0) -> dict[str, object]:
    body: dict[str, object] = json.loads(route.calls[call].request.content)
    return body


@respx.mock
async def test_text_send_body_and_receipt(sender: WhatsAppSender) -> None:
    route = respx.post(MESSAGES_URL).respond(200, json=SENT)
    receipt = await sender.send(part(PartKind.TEXT, text="Namaste"), RECIPIENT)
    assert receipt.provider_message_id == "wamid.OUT1"
    assert receipt.sent_at == NOW
    assert sent_json(route) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "919000000001",
        "type": "text",
        "text": {"body": "Namaste", "preview_url": False},
    }
    assert route.calls[0].request.headers["authorization"] == "Bearer token-for-tests"


@pytest.mark.parametrize("length", [0, 4097])
async def test_text_outside_limits_is_refused_not_truncated(
    sender: WhatsAppSender, length: int
) -> None:
    with pytest.raises(ValueError, match=r"1\.\.4096"):
        await sender.send(part(PartKind.TEXT, text="a" * length), RECIPIENT)


@respx.mock
async def test_text_of_exactly_4096_chars_is_sent(sender: WhatsAppSender) -> None:
    respx.post(MESSAGES_URL).respond(200, json=SENT)
    await sender.send(part(PartKind.TEXT, text="a" * 4096), RECIPIENT)


@respx.mock
async def test_interactive_buttons(sender: WhatsAppSender) -> None:
    route = respx.post(MESSAGES_URL).respond(200, json=SENT)
    buttons = [
        ReplyButton(id="onb:consent:yes", title="Haan, theek hai"),
        ReplyButton(id="onb:consent:no", title="Nahi"),
    ]
    await sender.send(
        part(PartKind.INTERACTIVE, text="Kya aap sahmat hain?", buttons=buttons), RECIPIENT
    )
    assert sent_json(route)["interactive"] == {
        "type": "button",
        "body": {"text": "Kya aap sahmat hain?"},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": "onb:consent:yes", "title": "Haan, theek hai"}},
                {"type": "reply", "reply": {"id": "onb:consent:no", "title": "Nahi"}},
            ]
        },
    }


async def test_four_buttons_are_refused(sender: WhatsAppSender) -> None:
    buttons = [ReplyButton(id=f"b{n}", title="t") for n in range(4)]
    with pytest.raises(ValueError, match=r"1\.\.3 buttons"):
        await sender.send(part(PartKind.INTERACTIVE, text="x", buttons=buttons), RECIPIENT)


def test_button_title_over_20_chars_is_refused_by_the_model() -> None:
    with pytest.raises(ValidationError, match="20"):
        ReplyButton(id="x", title="a" * 21)


@respx.mock
async def test_voice_note_uploads_then_sends(sender: WhatsAppSender) -> None:
    upload = respx.post(MEDIA_URL).respond(200, json={"id": "MEDIA42"})
    send = respx.post(MESSAGES_URL).respond(200, json=SENT)
    clip = AudioClip(data=b"OggS-voice", mime_type="audio/ogg; codecs=opus", duration_ms=2000)
    await sender.send(part(PartKind.AUDIO, audio_blob_id=uuid4()), RECIPIENT, audio=clip)
    assert b'name="messaging_product"' in upload.calls[0].request.content
    assert b"OggS-voice" in upload.calls[0].request.content
    assert sent_json(send)["audio"] == {"id": "MEDIA42"}


async def test_non_opus_audio_is_refused(sender: WhatsAppSender) -> None:
    clip = AudioClip(data=b"x", mime_type="audio/ogg", duration_ms=None)
    with pytest.raises(ValueError, match="codecs=opus"):
        await sender.send(part(PartKind.AUDIO, audio_blob_id=uuid4()), RECIPIENT, audio=clip)


async def test_audio_part_without_bytes_is_refused(sender: WhatsAppSender) -> None:
    with pytest.raises(ValueError, match="audio_blob_id and the clip"):
        await sender.send(part(PartKind.AUDIO, audio_blob_id=uuid4()), RECIPIENT)


@respx.mock
async def test_image_card_uploads_then_sends_with_caption(sender: WhatsAppSender) -> None:
    respx.post(MEDIA_URL).respond(200, json={"id": "IMG42"})
    send = respx.post(MESSAGES_URL).respond(200, json=SENT)
    card = ImageClip(data=b"\x89PNG-card", mime_type="image/png")
    await sender.send(
        part(PartKind.IMAGE, image_blob_id=uuid4(), text="Munni ne parchhai ka raaz khoja!"),
        RECIPIENT,
        image=card,
    )
    assert sent_json(send)["image"] == {
        "id": "IMG42",
        "caption": "Munni ne parchhai ka raaz khoja!",
    }


async def test_image_caption_over_1024_is_refused(sender: WhatsAppSender) -> None:
    card = ImageClip(data=b"x", mime_type="image/png")
    with pytest.raises(ValueError, match="1024"):
        await sender.send(
            part(PartKind.IMAGE, image_blob_id=uuid4(), text="a" * 1025), RECIPIENT, image=card
        )


async def test_image_part_without_bytes_is_refused(sender: WhatsAppSender) -> None:
    with pytest.raises(ValueError, match="image's bytes"):
        await sender.send(part(PartKind.IMAGE, image_blob_id=uuid4()), RECIPIENT)


@respx.mock
async def test_template_with_quick_reply_payload(sender: WhatsAppSender) -> None:
    send = respx.post(MESSAGES_URL).respond(200, json=SENT)
    template = TemplateRef(name="aaj_ki_khoj", language_code="hi", button_payloads=["jrn:today"])
    await sender.send(part(PartKind.TEMPLATE, template=template), RECIPIENT)
    assert sent_json(send)["template"] == {
        "name": "aaj_ki_khoj",
        "language": {"code": "hi"},
        "components": [
            {"type": "button", "sub_type": "quick_reply", "index": "0",
             "parameters": [{"type": "payload", "payload": "jrn:today"}]},
        ],
    }  # fmt: skip


@respx.mock
async def test_hello_world_template_has_no_components(sender: WhatsAppSender) -> None:
    send = respx.post(MESSAGES_URL).respond(200, json=SENT)
    template = TemplateRef(name="hello_world", language_code="en_US", button_payloads=[])
    await sender.send(part(PartKind.TEMPLATE, template=template), RECIPIENT)
    assert sent_json(send)["template"] == {"name": "hello_world", "language": {"code": "en_US"}}


@pytest.mark.parametrize("extra", [{"text": "x"}, {"template": None}])
async def test_malformed_template_parts_are_refused(
    sender: WhatsAppSender, extra: dict[str, object]
) -> None:
    fields: dict[str, object] = {
        "template": TemplateRef(name="t", language_code="hi", button_payloads=[])
    }
    fields.update(extra)
    with pytest.raises(ValueError, match="template"):
        await sender.send(part(PartKind.TEMPLATE, **fields), RECIPIENT)


async def test_web_address_is_refused(sender: WhatsAppSender) -> None:
    web = ChannelAddress(channel=Channel.WEB, address=SecretStr("abc"))
    with pytest.raises(ValueError, match="can't send to a web address"):
        await sender.send(part(PartKind.TEXT, text="hi"), web)


@respx.mock
async def test_acknowledge_marks_read_with_typing_indicator(sender: WhatsAppSender) -> None:
    route = respx.post(MESSAGES_URL).respond(200, json={"success": True})
    await sender.acknowledge("wamid.IN1")
    assert sent_json(route) == {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": "wamid.IN1",
        "typing_indicator": {"type": "text"},
    }


@respx.mock
@pytest.mark.parametrize(
    ("status_code", "code", "error_type"),
    [
        (400, 131047, ProviderRejected),
        (400, 131026, ProviderRejected),
        (401, 190, ProviderRejected),
        (400, 132001, ProviderRejected),
        (429, 130429, ProviderRateLimited),
        (400, 131056, ProviderRateLimited),
        (500, 131000, ProviderUnavailable),
        (503, None, ProviderUnavailable),
    ],
)
async def test_graph_errors_raise_typed_errors(
    sender: WhatsAppSender, status_code: int, code: int | None, error_type: type[Exception]
) -> None:
    body = {"error": {"message": "m", "type": "OAuthException", "code": code}} if code else {}
    respx.post(MESSAGES_URL).respond(status_code, json=body)
    with pytest.raises(error_type):
        await sender.send(part(PartKind.TEXT, text="hi"), RECIPIENT)


@respx.mock
async def test_timeout_becomes_provider_timeout(sender: WhatsAppSender) -> None:
    respx.post(MESSAGES_URL).mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(ProviderTimeout, match="timed out"):
        await sender.send(part(PartKind.TEXT, text="hi"), RECIPIENT)


@respx.mock
async def test_connection_error_becomes_unavailable(sender: WhatsAppSender) -> None:
    respx.post(MESSAGES_URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ProviderUnavailable, match="unreachable"):
        await sender.send(part(PartKind.TEXT, text="hi"), RECIPIENT)


@respx.mock
@pytest.mark.parametrize("body", [{}, {"messages": []}, {"unexpected": True}])
async def test_unexpected_success_body_is_invalid_response(
    sender: WhatsAppSender, body: dict[str, object]
) -> None:
    respx.post(MESSAGES_URL).respond(200, json=body)
    with pytest.raises(ProviderResponseInvalid):
        await sender.send(part(PartKind.TEXT, text="hi"), RECIPIENT)


@pytest.mark.parametrize(
    ("status_code", "body", "error_type", "retryable"),
    [
        (400, b'{"error":{"code":4}}', ProviderRateLimited, True),
        (400, b'{"error":{"code":80007}}', ProviderRateLimited, True),
        (400, b'{"error":{"code":131016}}', ProviderUnavailable, True),
        (400, b'{"error":{"code":131049}}', ProviderRejected, False),
        (400, b'{"error":{"code":131051}}', ProviderRejected, False),
        (400, b'{"error":{"code":368}}', ProviderRejected, False),
        (400, b'{"error":{"code":132015}}', ProviderRejected, False),
        (400, b"not json at all", ProviderRejected, False),
        (502, b"<html>bad gateway</html>", ProviderUnavailable, True),
    ],
)
def test_classify_graph_error(
    status_code: int, body: bytes, error_type: type[Exception], *, retryable: bool
) -> None:
    error = GraphErrorClassifier.classify(status_code, body)
    assert type(error) is error_type
    assert error.retryable is retryable
