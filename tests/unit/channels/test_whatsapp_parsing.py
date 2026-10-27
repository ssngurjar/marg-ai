import json
from datetime import UTC, datetime

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st
from pydantic import ValidationError

from app.channels.whatsapp.parsed_webhook import ParsedWebhook
from app.channels.whatsapp.payloads import WebhookBody
from app.channels.whatsapp.webhook_parser import WhatsAppWebhookParser
from app.core.types import JsonValue
from app.domain.enums import MessageKind, OutboxStatus
from app.domain.models.message import InboundMessage
from tests.support import whatsapp_payloads as wa
from tests.support.app_factory import TEST_PHONE_NUMBER_ID, make_identity

pytestmark = pytest.mark.unit

RECEIVED_AT = datetime(2025, 10, 27, 8, 0, 1, tzinfo=UTC)


def parse(payload: dict[str, JsonValue]) -> ParsedWebhook:
    body = WebhookBody.model_validate(payload)
    return WhatsAppWebhookParser.parse(body, TEST_PHONE_NUMBER_ID, make_identity(), RECEIVED_AT)


def only_message(payload: dict[str, JsonValue]) -> InboundMessage:
    parsed = parse(payload)
    assert len(parsed.messages) == 1
    return parsed.messages[0].inbound


def test_text_message() -> None:
    inbound = only_message(wa.webhook([wa.text_message("mujhe doctor banna hai")]))
    assert inbound.kind is MessageKind.TEXT
    assert inbound.text == "mujhe doctor banna hai"
    assert inbound.external_id == "wamid.TEST1"
    assert inbound.provider_sent_at == datetime(2025, 10, 27, 8, 0, tzinfo=UTC)
    assert inbound.received_at == RECEIVED_AT
    assert inbound.user_hash == make_identity().user_hash("whatsapp", wa.FAKE_WA_ID)


@pytest.mark.parametrize("voice", [True, False])
def test_voice_note_and_forwarded_audio(*, voice: bool) -> None:
    inbound = only_message(wa.webhook([wa.voice_note("MEDIA9", voice=voice)]))
    assert inbound.kind is MessageKind.AUDIO
    assert inbound.media is not None
    assert inbound.media.provider_media_id == "MEDIA9"
    assert inbound.media.mime_type.startswith("audio/ogg")
    assert inbound.text is None


def test_image_with_caption_maps_to_image_kind() -> None:
    inbound = only_message(wa.webhook([wa.image_message("Munni ke patte")]))
    assert inbound.kind is MessageKind.IMAGE
    assert inbound.text == "Munni ke patte"
    assert inbound.media is not None
    assert inbound.media.provider_media_id == "IMG1"


def test_image_without_caption() -> None:
    assert only_message(wa.webhook([wa.image_message(None)])).text is None


def test_button_reply() -> None:
    inbound = only_message(wa.webhook([wa.button_reply("onb:consent:yes", "Haan, theek hai")]))
    assert inbound.kind is MessageKind.INTERACTIVE
    assert inbound.interactive_reply_id == "onb:consent:yes"
    assert inbound.text == "Haan, theek hai"


def test_list_reply() -> None:
    inbound = only_message(wa.webhook([wa.list_reply("row:2", "Doosra bachcha")]))
    assert inbound.interactive_reply_id == "row:2"


def test_template_quick_reply_maps_to_interactive_with_payload() -> None:
    inbound = only_message(wa.webhook([wa.template_quick_reply("jrn:today")]))
    assert inbound.kind is MessageKind.INTERACTIVE
    assert inbound.interactive_reply_id == "jrn:today"


@pytest.mark.parametrize(
    "message_type",
    ["sticker", "video", "document", "location", "contacts", "unsupported", "brand_new_type"],
)
def test_other_types_become_unsupported_not_dropped(message_type: str) -> None:
    inbound = only_message(wa.webhook([wa.message(message_type, {message_type: {"id": "X"}})]))
    assert inbound.kind is MessageKind.UNSUPPORTED


def test_type_with_missing_sub_object_is_unsupported() -> None:
    inbound = only_message(wa.webhook([wa.message("audio")]))
    assert inbound.kind is MessageKind.UNSUPPORTED


def test_interactive_without_reply_is_unsupported() -> None:
    payload = wa.webhook([wa.message("interactive", {"interactive": {"type": "button_reply"}})])
    assert only_message(payload).kind is MessageKind.UNSUPPORTED


@pytest.mark.parametrize("message_type", ["reaction", "system"])
def test_reactions_and_system_messages_are_not_stored(message_type: str) -> None:
    parsed = parse(wa.webhook([wa.message(message_type, {message_type: {}})]))
    assert parsed.messages == []
    assert parsed.ignored == 1


@pytest.mark.parametrize(
    "broken",
    [
        {"from": wa.FAKE_WA_ID, "timestamp": wa.SENT_AT, "type": "text"},  # no id
        {"id": "wamid.X", "timestamp": wa.SENT_AT, "type": "text"},  # no sender
        {"from": wa.FAKE_WA_ID, "id": "wamid.X", "timestamp": "yesterday", "type": "text"},
    ],
)
def test_malformed_message_is_counted_not_stored(broken: dict[str, JsonValue]) -> None:
    parsed = parse(wa.webhook([broken, wa.text_message(message_id="wamid.OK")]))
    assert parsed.malformed == 1
    assert [item.inbound.external_id for item in parsed.messages] == ["wamid.OK"]


def test_foreign_phone_number_id_is_ignored() -> None:
    parsed = parse(wa.webhook([wa.text_message()], phone_number_id="999"))
    assert parsed.messages == []
    assert parsed.foreign_phone_number_id == 1


def test_other_field_and_other_object_are_ignored() -> None:
    assert parse(wa.webhook([wa.text_message()], field="account_update")).ignored == 1
    assert parse(wa.webhook([wa.text_message()], object_name="page")).ignored == 1


def test_account_update_without_messaging_product_is_ignored_not_unparseable() -> None:
    # Regression: the first live webhook after subscribing the app was rejected as unparseable.
    payload: dict[str, JsonValue] = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WABA1", "changes": [wa.account_update_change()]}],
    }
    parsed = parse(payload)
    assert parsed.ignored == 1
    assert parsed.messages == []
    assert parsed.malformed == 0


@pytest.mark.parametrize("value", [None, "text", 7, [], {}], ids=repr)
def test_other_field_with_any_value_shape_is_ignored(value: JsonValue) -> None:
    payload: dict[str, JsonValue] = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WABA1", "changes": [{"field": "security", "value": value}]}],
    }
    assert parse(payload).ignored == 1


def test_message_batched_with_another_field_is_still_stored() -> None:
    payload = wa.with_extra_change(wa.webhook([wa.text_message()]), wa.account_update_change())
    parsed = parse(payload)
    assert len(parsed.messages) == 1
    assert parsed.ignored == 1


@pytest.mark.parametrize("missing", ["messaging_product", "metadata"])
def test_messages_change_missing_required_part_is_still_rejected(missing: str) -> None:
    # Only other fields are lenient: a broken `messages` change must not pass as "other".
    payload = wa.webhook([wa.text_message()])
    entries = payload["entry"]
    assert isinstance(entries, list)
    entry = entries[0]
    assert isinstance(entry, dict)
    changes = entry["changes"]
    assert isinstance(changes, list)
    change = changes[0]
    assert isinstance(change, dict)
    value = change["value"]
    assert isinstance(value, dict)
    del value[missing]
    with pytest.raises(ValidationError, match=missing):
        WebhookBody.model_validate(payload)


def test_profile_name_and_number_never_reach_parsed_messages() -> None:
    parsed = parse(wa.webhook([wa.text_message("hello")]))
    item = parsed.messages[0]
    serialised = item.inbound.model_dump_json() + json.dumps(item.raw_payload)
    assert wa.PROFILE_NAME not in serialised
    assert wa.FAKE_WA_ID not in serialised
    assert item.wa_id.get_secret_value() == wa.FAKE_WA_ID  # kept only to encrypt the address


def test_stripped_payload_drops_urls_hashes_and_captions() -> None:
    raw = parse(wa.webhook([wa.image_message("private caption")])).messages[0].raw_payload
    assert raw["image"] == {"id": "IMG1", "mime_type": "image/jpeg"}
    assert "private caption" not in json.dumps(raw)
    audio = parse(wa.webhook([wa.voice_note()])).messages[0].raw_payload["audio"]
    assert isinstance(audio, dict)
    assert "url" not in audio


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("sent", OutboxStatus.SENT),
        ("delivered", OutboxStatus.DELIVERED),
        ("read", OutboxStatus.READ),
        ("played", OutboxStatus.READ),
        ("failed", OutboxStatus.FAILED),
    ],
)
def test_status_updates(state: str, expected: OutboxStatus) -> None:
    parsed = parse(wa.webhook(statuses=[wa.status(state)]))
    assert [update.status for update in parsed.statuses] == [expected]
    assert parsed.messages == []


def test_failed_status_carries_error_code_but_never_the_recipient() -> None:
    update = parse(wa.webhook(statuses=[wa.status("failed", error_code=131047)])).statuses[0]
    assert update.error_code == 131047
    assert wa.FAKE_WA_ID not in update.model_dump_json()


def test_unknown_status_value_is_malformed() -> None:
    parsed = parse(wa.webhook(statuses=[wa.status("exploded")]))
    assert parsed.statuses == []
    assert parsed.malformed == 1


def test_batch_of_messages_and_statuses() -> None:
    payload = wa.webhook(
        [
            wa.text_message(message_id="wamid.A"),
            wa.voice_note(),
            wa.template_quick_reply(),
        ],
        [wa.status("delivered"), wa.status("read")],
    )
    parsed = parse(payload)
    assert len(parsed.messages) == 3
    assert len(parsed.statuses) == 2


def test_account_level_errors_are_collected() -> None:
    value: dict[str, JsonValue] = {
        "messaging_product": "whatsapp",
        "metadata": {
            "display_phone_number": "15550001111",
            "phone_number_id": TEST_PHONE_NUMBER_ID,
        },
        "errors": [{"code": 131042, "title": "Business eligibility payment issue"}],
    }
    payload: dict[str, JsonValue] = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WABA1", "changes": [{"field": "messages", "value": value}]}],
    }
    assert [error.code for error in parse(payload).account_errors] == [131042]


# --- properties ---------------------------------------------------------------------------------

_TEXT = st.text(max_size=60)


@given(wa_id=st.text(alphabet="0123456789", min_size=10, max_size=13), caption=_TEXT, body=_TEXT,
       reply_to_sender=st.booleans())  # fmt: skip
def test_property_stripped_payload_never_contains_the_number(
    wa_id: str, caption: str, body: str, *, reply_to_sender: bool
) -> None:
    assume(wa_id not in body and wa_id not in caption)
    caption = f"CAPTION-MARKER {caption}"  # distinctive, so finding it can only mean a leak
    text = wa.message("text", {"text": {"body": body}}, wa_id=wa_id)
    if reply_to_sender:
        text["context"] = {"id": "wamid.PREV", "from": wa_id}
    image = wa.message(
        "image",
        {
            "image": {
                "id": "I",
                "mime_type": "image/png",
                "caption": caption,
                "url": f"https://x/{wa_id}",
            }
        },
        wa_id=wa_id,
        message_id="wamid.IMG",
    )
    for item in parse(wa.webhook([text, image])).messages:
        serialised = json.dumps(item.raw_payload)
        assert wa_id not in serialised
        assert '"url"' not in serialised
        assert "CAPTION-MARKER" not in serialised


_MESSAGE_SPECS = st.one_of(
    st.tuples(st.just("text"), st.text(min_size=1, max_size=40)),
    st.tuples(st.just("button"), st.text(alphabet="abcdefghijklmnop:", min_size=1, max_size=20)),
    st.tuples(st.just("audio"), st.text(alphabet="ABCDEF0123456789", min_size=1, max_size=20)),
    st.tuples(st.text(alphabet="xyzqw", min_size=3, max_size=8), st.just("")),
)


@given(
    spec=_MESSAGE_SPECS, unix_seconds=st.integers(min_value=1_000_000_000, max_value=4_000_000_000)
)
def test_property_parse_round_trip(spec: tuple[str, str], unix_seconds: int) -> None:
    message_type, value = spec
    fields: dict[str, JsonValue]
    if message_type == "text":
        fields = {"text": {"body": value}}
    elif message_type == "button":
        fields = {"button": {"payload": value, "text": "t"}}
    elif message_type == "audio":
        fields = {"audio": {"id": value, "mime_type": "audio/ogg; codecs=opus"}}
    else:
        fields = {}
    raw = wa.message(message_type, fields)
    raw["timestamp"] = str(unix_seconds)
    inbound = only_message(wa.webhook([raw]))
    assert inbound.provider_sent_at == datetime.fromtimestamp(unix_seconds, UTC)
    if message_type == "text":
        assert (inbound.kind, inbound.text) == (MessageKind.TEXT, value)
    elif message_type == "button":
        assert (inbound.kind, inbound.interactive_reply_id) == (MessageKind.INTERACTIVE, value)
    elif message_type == "audio":
        assert inbound.media is not None
        assert (inbound.kind, inbound.media.provider_media_id) == (MessageKind.AUDIO, value)
    else:
        assert inbound.kind is MessageKind.UNSUPPORTED
