"""WebMessageParser: a demo visitor's message, validated once (s14 §4.3)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.channels.web.web_message_parser import (
    WebButton,
    WebLimits,
    WebMessageParser,
    WebPhoto,
    WebText,
    WebUpload,
    WebVoice,
)
from app.core.errors import WebInputInvalid

pytestmark = pytest.mark.unit

CAP = 1000
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 20
OGG = b"OggS" + b"\x00" * 20
MP4 = b"\x00\x00\x00\x18ftypM4A " + b"\x00" * 10


def upload(
    text: str | None = None,
    audio: bytes | None = None,
    audio_type: str | None = None,
    button_id: str | None = None,
) -> WebUpload:
    return WebUpload(text=text, audio=audio, audio_type=audio_type, button_id=button_id)


def parse(sent: WebUpload, offered: set[str] | None = None) -> object:
    return WebMessageParser.parse(sent, WebLimits(CAP, CAP), offered or set())


def refused(sent: WebUpload, field: str, reason: str, offered: set[str] | None = None) -> None:
    with pytest.raises(WebInputInvalid, match=f"{field}: {reason}"):
        parse(sent, offered)


def test_text_is_trimmed() -> None:
    assert parse(upload(text="  Hi  ")) == WebText("Hi")


@pytest.mark.parametrize(
    ("data", "declared"),
    [(WEBM, "audio/webm;codecs=opus"), (OGG, "audio/ogg"), (MP4, "audio/mp4")],
)
def test_each_browser_recording_format_is_taken(data: bytes, declared: str) -> None:
    voice = parse(upload(audio=data, audio_type=declared))
    assert isinstance(voice, WebVoice)
    assert voice.mime_type == declared.split(";", maxsplit=1)[0]


def test_a_button_from_the_latest_reply_is_taken() -> None:
    assert parse(upload(button_id="onb:consent:yes"), {"onb:consent:yes"}) == WebButton(
        "onb:consent:yes"
    )


def test_nothing_or_two_things_are_refused() -> None:
    refused(upload(), "message", "none_provided")
    refused(upload(text="Hi", button_id="jrn:today"), "message", "multiple_provided")


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_blank_text_is_refused(text: str) -> None:
    refused(upload(text=text), "text", "empty")


def test_text_of_exactly_1000_is_taken_and_1001_refused() -> None:
    assert isinstance(parse(upload(text="a" * 1000)), WebText)
    refused(upload(text="a" * 1001), "text", "too_long")


def test_audio_at_the_cap_is_taken_and_one_byte_more_refused() -> None:
    assert isinstance(
        parse(upload(audio=WEBM + b"\x00" * (CAP - len(WEBM)), audio_type="audio/webm")), WebVoice
    )
    refused(
        upload(audio=WEBM + b"\x00" * (CAP - len(WEBM) + 1), audio_type="audio/webm"),
        "audio",
        "too_large",
    )


@pytest.mark.parametrize(
    ("data", "declared", "reason"),
    [
        (b"", "audio/webm", "empty"),
        (WEBM, "video/mp4", "unsupported_type"),
        (WEBM, None, "unsupported_type"),
        (OGG, "audio/webm", "type_mismatch"),
        (b"MZ\x90\x00 an exe", "audio/ogg", "type_mismatch"),
    ],
)
def test_wrong_or_mislabelled_audio_is_refused(
    data: bytes, declared: str | None, reason: str
) -> None:
    refused(upload(audio=data, audio_type=declared), "audio", reason)


@pytest.mark.parametrize("button", ["onb:delete:yes", "nudge:08", "ONB:CONSENT:YES", "a b", ""])
def test_a_button_not_offered_or_malformed_is_refused(button: str) -> None:
    refused(upload(button_id=button), "button_id", "unknown_button", {"onb:consent:yes"})


@given(text=st.text(min_size=1, max_size=1000).filter(lambda value: value.strip()))
def test_any_non_blank_text_up_to_the_limit_is_taken(text: str) -> None:
    parsed = parse(upload(text=text))
    assert isinstance(parsed, WebText)
    assert parsed.text == text.strip()


# --- photos (s10b §4.14) --------------------------------------------------------------------------

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 10


def photo_upload(data: bytes, declared: str | None) -> WebUpload:
    return WebUpload(
        text=None, audio=None, audio_type=None, button_id=None, image=data, image_type=declared
    )


@pytest.mark.parametrize(
    ("data", "declared"),
    [(JPEG, "image/jpeg"), (PNG, "image/png"), (WEBP, "image/webp"), (JPEG, "IMAGE/JPEG; q=1")],
)
def test_each_photo_format_is_taken(data: bytes, declared: str) -> None:
    taken = parse(photo_upload(data, declared))
    expected_type = declared.split(";", maxsplit=1)[0].strip().lower()
    assert taken == WebPhoto(data=data, mime_type=expected_type)


def test_a_photo_at_the_cap_is_taken_and_one_byte_more_refused() -> None:
    at_cap = JPEG + b"\x00" * (CAP - len(JPEG))
    assert isinstance(parse(photo_upload(at_cap, "image/jpeg")), WebPhoto)
    refused(photo_upload(at_cap + b"\x00", "image/jpeg"), "image", "too_large")


@pytest.mark.parametrize(
    ("data", "declared", "reason"),
    [
        (b"", "image/jpeg", "empty"),
        (JPEG, "image/gif", "unsupported_type"),
        (JPEG, None, "unsupported_type"),
        (PNG, "image/jpeg", "type_mismatch"),
        (b"<svg onload=alert(1)>", "image/png", "type_mismatch"),
        (WEBM, "image/webp", "type_mismatch"),
    ],
)
def test_wrong_or_mislabelled_photos_are_refused(
    data: bytes, declared: str | None, reason: str
) -> None:
    refused(photo_upload(data, declared), "image", reason)


def test_a_photo_with_anything_else_is_refused() -> None:
    both = WebUpload(
        text="Munni ka minar",
        audio=None,
        audio_type=None,
        button_id=None,
        image=JPEG,
        image_type="image/jpeg",
    )
    refused(both, "message", "multiple_provided")
