"""Realistic WhatsApp Cloud API webhook payloads for tests (shapes from Meta's webhook docs).

Numbers are fake (91900000xxxx); a real person's number never goes into a test.
"""

import hashlib
import hmac
import json

from app.core.types import JsonValue
from tests.support.app_factory import APP_SIGNING_KEY_FOR_TESTS, TEST_PHONE_NUMBER_ID

FAKE_WA_ID = "919000000001"
SENT_AT = "1761552000"  # 2025-10-27T08:00:00Z
PROFILE_NAME = "Sunita Devi"  # WhatsApp sends the profile name; we must never store it


def message(
    message_type: str,
    fields: dict[str, JsonValue] | None = None,
    *,
    wa_id: str = FAKE_WA_ID,
    message_id: str = "wamid.TEST1",
) -> dict[str, JsonValue]:
    return {
        "from": wa_id,
        "id": message_id,
        "timestamp": SENT_AT,
        "type": message_type,
        **(fields or {}),
    }


def text_message(
    body: str = "mujhe doctor banna hai", *, message_id: str = "wamid.TEST1"
) -> dict[str, JsonValue]:
    return message("text", {"text": {"body": body}}, message_id=message_id)


def voice_note(
    media_id: str = "MEDIA1", *, voice: bool = True, message_id: str = "wamid.TEST1"
) -> dict[str, JsonValue]:
    audio: dict[str, JsonValue] = {
        "id": media_id,
        "mime_type": "audio/ogg; codecs=opus",
        "sha256": "abc",
        "voice": voice,
        "url": "https://lookaside.example/media",
    }
    return message("audio", {"audio": audio}, message_id=message_id)


def image_message(caption: str | None = "Munni ke patte") -> dict[str, JsonValue]:
    image: dict[str, JsonValue] = {
        "id": "IMG1",
        "mime_type": "image/jpeg",
        "sha256": "def",
        "url": "https://lookaside.example/img",
    }
    if caption is not None:
        image["caption"] = caption
    return message("image", {"image": image})


def button_reply(
    button_id: str = "onb:consent:yes",
    title: str = "Haan, theek hai",
    *,
    message_id: str = "wamid.TEST1",
) -> dict[str, JsonValue]:
    reply: dict[str, JsonValue] = {"id": button_id, "title": title}
    return message(
        "interactive",
        {"interactive": {"type": "button_reply", "button_reply": reply}},
        message_id=message_id,
    )


def list_reply(row_id: str = "row:1", title: str = "Pehla bachcha") -> dict[str, JsonValue]:
    row: dict[str, JsonValue] = {"id": row_id, "title": title}
    return message("interactive", {"interactive": {"type": "list_reply", "list_reply": row}})


def template_quick_reply(payload: str = "jrn:today") -> dict[str, JsonValue]:
    return message("button", {"button": {"payload": payload, "text": "Aaj ki khoj batao"}})


def status(
    state: str, message_id: str = "wamid.OUT1", *, error_code: int | None = None
) -> dict[str, JsonValue]:
    entry: dict[str, JsonValue] = {
        "id": message_id,
        "status": state,
        "timestamp": SENT_AT,
        "recipient_id": FAKE_WA_ID,
    }
    if error_code is not None:
        entry["errors"] = [{"code": error_code, "title": "Re-engagement message"}]
    return entry


def webhook(
    messages: list[dict[str, JsonValue]] | None = None,
    statuses: list[dict[str, JsonValue]] | None = None,
    *,
    phone_number_id: str = TEST_PHONE_NUMBER_ID,
    field: str = "messages",
    object_name: str = "whatsapp_business_account",
) -> dict[str, JsonValue]:
    value: dict[str, JsonValue] = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "15550001111", "phone_number_id": phone_number_id},
        "contacts": [{"profile": {"name": PROFILE_NAME}, "wa_id": FAKE_WA_ID}],
    }
    if messages is not None:
        value["messages"] = list(messages)
    if statuses is not None:
        value["statuses"] = list(statuses)
    return {
        "object": object_name,
        "entry": [{"id": "WABA1", "changes": [{"field": field, "value": value}]}],
    }


def account_update_change() -> dict[str, JsonValue]:
    """The change Meta sends when an app is subscribed to the account: no messaging_product,
    no metadata. The first real webhook in the S3 exit check was one of these."""
    return {
        "field": "account_update",
        "value": {
            "event": "PARTNER_APP_INSTALLED",
            "waba_info": {
                "waba_id": "WABA1",
                "owner_business_id": "BIZ1",
                "partner_app_id": "APP1",
            },
        },
    }


def with_extra_change(
    payload: dict[str, JsonValue], change: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    """The same webhook with one more change appended to its first entry."""
    entries = payload["entry"]
    assert isinstance(entries, list)
    first_entry = entries[0]
    assert isinstance(first_entry, dict)
    changes = first_entry["changes"]
    assert isinstance(changes, list)
    return {**payload, "entry": [{**first_entry, "changes": [*changes, change]}]}


def signed(
    payload: dict[str, JsonValue] | bytes, secret: str = APP_SIGNING_KEY_FOR_TESTS
) -> tuple[bytes, str]:
    """(raw body, X-Hub-Signature-256 header) exactly as Meta would send them."""
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    digest = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, f"sha256={digest}"
