"""GraphMessageBuilder: the JSON body for each kind of outbound part (s03 §4.9). Pure.

Limits are enforced before anything is sent: a malformed part is a bug upstream, so it raises
ValueError instead of being truncated.
"""

from app.constants.whatsapp import (
    IMAGE_MIMES,
    MAX_AUDIO_BYTES,
    MAX_BUTTONS,
    MAX_CAPTION_CHARS,
    MAX_IMAGE_BYTES,
    MAX_INTERACTIVE_BODY_CHARS,
    MAX_TEXT_CHARS,
    VOICE_NOTE_MIME,
)
from app.core.types import JsonValue
from app.domain.models.message import AudioClip, ImageClip
from app.domain.models.reply import OutboundPart


class GraphMessageBuilder:
    @staticmethod
    def text_body(part: OutboundPart) -> dict[str, JsonValue]:
        body = part.text or ""
        if not 1 <= len(body) <= MAX_TEXT_CHARS:
            raise ValueError(f"text part must be 1..{MAX_TEXT_CHARS} chars, got {len(body)}")
        # No link previews: a preview is content in a child's chat that we didn't check.
        return {"type": "text", "text": {"body": body, "preview_url": False}}

    @staticmethod
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
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "action": {"buttons": buttons},
            },
        }

    @staticmethod
    def template_body(part: OutboundPart) -> dict[str, JsonValue]:
        if part.template is None:
            raise ValueError("template part has no template")
        if (
            part.text is not None
            or part.audio_blob_id is not None
            or part.image_blob_id is not None
        ):
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

    @staticmethod
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

    @staticmethod
    def require_image(part: OutboundPart, image: ImageClip | None) -> ImageClip:
        if part.image_blob_id is None or image is None:
            raise ValueError("image part needs image_blob_id and the image's bytes")
        if image.mime_type not in IMAGE_MIMES:
            raise ValueError(f"WhatsApp images must be one of {sorted(IMAGE_MIMES)}")
        if not 0 < len(image.data) <= MAX_IMAGE_BYTES:
            raise ValueError(f"image must be 1..{MAX_IMAGE_BYTES} bytes")
        if part.text is not None and len(part.text) > MAX_CAPTION_CHARS:
            raise ValueError(
                f"caption must be at most {MAX_CAPTION_CHARS} chars, got {len(part.text)}"
            )
        return image
