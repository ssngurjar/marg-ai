"""WebMessageParser: what a web demo visitor sent, validated once at the edge (s14 §4.3).

Exactly one of: typed text, a recorded voice note, or a button from the visitor's latest reply.
A voice note's declared type must agree with its first bytes, so a mislabelled file is refused
here, not by ffmpeg later. Nothing is repaired: bad input is refused with a fixed reason.
"""

import re
from dataclasses import dataclass
from typing import ClassVar, Final

from app.core.errors import WebInputInvalid

MAX_TEXT_CHARS: Final = 1000


@dataclass(frozen=True, slots=True)
class WebText:
    text: str


@dataclass(frozen=True, slots=True)
class WebVoice:
    data: bytes
    mime_type: str  # the declared type, without parameters ("audio/webm")


@dataclass(frozen=True, slots=True)
class WebButton:
    button_id: str


type WebMessage = WebText | WebVoice | WebButton


@dataclass(frozen=True, slots=True)
class WebUpload:
    """The raw form fields: None when absent."""

    text: str | None
    audio: bytes | None
    audio_type: str | None
    button_id: str | None


class WebMessageParser:
    BUTTON_ID: ClassVar[re.Pattern[str]] = re.compile(r"^[a-z0-9:_-]{1,256}$")
    AUDIO_SIGNATURES: ClassVar[dict[str, tuple[int, bytes]]] = {
        "audio/webm": (0, b"\x1a\x45\xdf\xa3"),
        "audio/ogg": (0, b"OggS"),
        "audio/mp4": (4, b"ftyp"),  # Safari records AAC in MP4
    }

    @staticmethod
    def parse(upload: WebUpload, max_audio_bytes: int, offered_buttons: set[str]) -> WebMessage:
        """Raises WebInputInvalid(field, reason)."""
        given = [
            name
            for name, value in (
                ("text", upload.text),
                ("audio", upload.audio),
                ("button_id", upload.button_id),
            )
            if value is not None
        ]
        if not given:
            raise WebInputInvalid("message", "none_provided")
        if len(given) > 1:
            raise WebInputInvalid("message", "multiple_provided")
        if upload.text is not None:
            return WebMessageParser._text(upload.text)
        if upload.audio is not None:
            return WebMessageParser._voice(upload.audio, upload.audio_type, max_audio_bytes)
        return WebMessageParser._button(upload.button_id or "", offered_buttons)

    @staticmethod
    def _text(text: str) -> WebText:
        trimmed = text.strip()
        if not trimmed:
            raise WebInputInvalid("text", "empty")
        if len(trimmed) > MAX_TEXT_CHARS:
            raise WebInputInvalid("text", "too_long")
        return WebText(trimmed)

    @staticmethod
    def _voice(data: bytes, declared: str | None, max_bytes: int) -> WebVoice:
        if not data:
            raise WebInputInvalid("audio", "empty")
        if len(data) > max_bytes:
            raise WebInputInvalid("audio", "too_large")
        mime_type = (declared or "").split(";")[0].strip().lower()
        signature = WebMessageParser.AUDIO_SIGNATURES.get(mime_type)
        if signature is None:
            raise WebInputInvalid("audio", "unsupported_type")
        offset, magic = signature
        if data[offset : offset + len(magic)] != magic:
            raise WebInputInvalid("audio", "type_mismatch")
        return WebVoice(data=data, mime_type=mime_type)

    @staticmethod
    def _button(button_id: str, offered: set[str]) -> WebButton:
        if not WebMessageParser.BUTTON_ID.match(button_id):
            raise WebInputInvalid("button_id", "unknown_button")
        if button_id not in offered:
            # a button from the visitor's latest reply only: onboarding answers can't be forged
            raise WebInputInvalid("button_id", "unknown_button")
        return WebButton(button_id)
