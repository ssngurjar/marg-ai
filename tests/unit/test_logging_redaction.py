import json
import re

import pytest
import structlog
from hypothesis import example, given
from hypothesis import strategies as st
from pydantic import SecretStr

from app.core.logging import (
    REDACTED,
    configure_logging,
    get_logger,
    redact_personal_data,
    redact_value,
)

pytestmark = pytest.mark.unit

USER_HASH = "a1b2c3d4" * 8  # 64 lowercase hex chars


@pytest.fixture(autouse=True)
def fresh_structlog() -> None:
    structlog.reset_defaults()


def render(event: dict[str, object]) -> str:
    """Run the redaction processor and render the result as the JSON line would be."""
    return json.dumps(redact_personal_data(None, "info", dict(event)), ensure_ascii=False)


def digits_only(text: str) -> str:
    return re.sub(r"\D", "", text)


@pytest.mark.parametrize(
    "event",
    [
        {"event": "x", "payload": {"from": "919812345678"}},
        {"event": "x", "items": [{"phone": "9812345678"}]},
        {"event": "x", "Authorization": "Bearer abc.def"},
        {"event": "x", "nested": {"deeper": {"transcript": "mujhe doctor banna hai"}}},
        {"event": "x", "TEXT": "case-insensitive key match"},
    ],
)
def test_redaction_denied_keys_at_any_depth(event: dict[str, object]) -> None:
    rendered = render(event)
    for value in ("919812345678", "9812345678", "abc.def", "mujhe doctor", "case-insensitive"):
        assert value not in rendered
    assert REDACTED in rendered


@pytest.mark.parametrize(
    "message",
    [
        "sending to +919812345678",
        "sending to +91 98123 45678",
        "sending to 98123-45678",
        "भेज रहे हैं 9812345678 पर",
    ],
)
def test_redaction_scans_event_message(message: str) -> None:
    assert "9812345678" not in digits_only(render({"event": message}))


def test_redaction_masks_bearer_and_opaque_tokens() -> None:
    rendered = render({"event": "auth Bearer sk_live_abc123 and key " + "Z" * 40})
    assert "sk_live_abc123" not in rendered
    assert "Z" * 40 not in rendered


def test_redaction_keeps_user_hash_and_uuid() -> None:
    turn_id = "550e8400-e29b-41d4-a716-446655440000"
    rendered = render({"event": f"turn {turn_id}", "user_hash": USER_HASH})
    assert USER_HASH in rendered
    assert turn_id in rendered


def test_redaction_handles_secretstr() -> None:
    rendered = render({"event": "x", "database": SecretStr("postgresql+asyncpg://u:pw@h/db")})
    assert "pw@h" not in rendered


def test_redaction_never_mutates_the_input() -> None:
    event: dict[str, object] = {"event": "call 9812345678", "phone": "9812345678"}
    redact_personal_data(None, "info", event)
    assert event == {"event": "call 9812345678", "phone": "9812345678"}


def fail_to_reach(number: str) -> None:
    raise ValueError(f"could not reach {number}")


def test_redaction_in_exception_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", environment="test")
    logger = get_logger("test")
    try:
        fail_to_reach("9812345678")
    except ValueError:
        logger.exception("send_failed")
    output = capsys.readouterr().out
    assert "send_failed" in output
    assert "9812345678" not in digits_only(output)


def test_logged_line_is_json_with_level_timestamp_and_environment(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", environment="test")
    get_logger("test").info("turn_started", user_hash=USER_HASH)
    line = json.loads(capsys.readouterr().out)
    assert line["event"] == "turn_started"
    assert line["level"] == "info"
    assert line["env"] == "test"
    assert line["user_hash"] == USER_HASH
    assert line["timestamp"].endswith("Z")


def test_log_level_filters_below_threshold(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING", environment="test")
    get_logger("test").info("quiet")
    assert capsys.readouterr().out == ""


# --- properties (CLAUDE.md §3) ---------------------------------------------------------------

DEVANAGARI_DIGITS = "".join(chr(code) for code in range(0x0966, 0x0970))

_NON_DIGIT_TEXT = st.text(
    alphabet=st.characters(
        categories=(
            "L",
            "Zs",
            "Po",
            "So",
        ),  # letters (incl. Devanagari), spaces, punctuation, emoji
        exclude_characters="+-0123456789" + DEVANAGARI_DIGITS,
    ),
    max_size=40,
)


@st.composite
def indian_mobile_numbers(draw: st.DrawFn) -> tuple[str, str]:
    """(as written, the 10 digits): realistic Indian formats with +91, spaces or dashes."""
    digits = draw(st.sampled_from("6789")) + "".join(
        draw(st.lists(st.sampled_from("0123456789"), min_size=9, max_size=9))
    )
    separator = draw(st.sampled_from(["", " ", "-"]))
    layout = draw(st.sampled_from(["10", "5-5", "3-3-4"]))
    if layout == "10":
        body = digits
    elif layout == "5-5":
        body = digits[:5] + separator + digits[5:]
    else:
        body = digits[:3] + separator + digits[3:6] + separator + digits[6:]
    prefix = draw(st.sampled_from(["", "+91", "+91 ", "+91-", "0"]))
    return prefix + body, digits


@given(before=_NON_DIGIT_TEXT, number=indian_mobile_numbers(), after=_NON_DIGIT_TEXT)
@example(before="", number=("+91 98123 45678", "9812345678"), after="")
def test_property_phone_numbers_never_survive(
    before: str, number: tuple[str, str], after: str
) -> None:
    written, digits = number
    rendered = render({"event": before + written + after, "note": after + written})
    assert digits not in digits_only(rendered)


_JSON_LIKE = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=30),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=10), children, max_size=4)
    ),
    max_leaves=20,
)


@given(event=st.dictionaries(st.text(min_size=1, max_size=10), _JSON_LIKE, max_size=6))
def test_property_redaction_is_idempotent(event: dict[str, object]) -> None:
    once = redact_personal_data(None, "info", dict(event))
    twice = redact_personal_data(None, "info", dict(once))
    assert once == twice


@given(value=_JSON_LIKE)
def test_property_redaction_never_raises_and_keeps_non_strings(value: object) -> None:
    redacted = redact_value("note", value)
    if value is None or isinstance(value, bool | int):
        assert redacted == value
