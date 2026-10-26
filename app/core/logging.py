"""Structured JSON logging with personal-data redaction (CLAUDE.md §11).

Every log line passes through `redact_personal_data` just before it's rendered, so phone numbers,
tokens, transcripts and replies can't reach the output, whatever the caller passes in.
Code outside `app/core` logs only through `get_logger`, which the layering test enforces.
"""

import logging
import re
from collections.abc import Mapping, Sequence
from typing import cast

import structlog
from pydantic import SecretStr
from structlog.typing import EventDict, FilteringBoundLogger, WrappedLogger

REDACTED = "[redacted]"

DENIED_KEYS = frozenset(
    {
        "phone", "wa_id", "from", "address", "recipient",
        "text", "body", "transcript", "user_text", "reply_text", "spoken_text", "caption",
        "profile", "name", "raw_payload", "payload",
        "authorization", "token", "access_token", "secret", "password", "api_key", "cookie",
    }
)  # fmt: skip
"""Keys whose values are never logged, at any depth. Matched case-insensitively."""

# Identifiers we log on purpose. They're protected from the patterns below, which would
# otherwise mistake their digit runs for phone numbers or their length for a token.
_USER_HASH = r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])"
_HEX = "[0-9a-fA-F]"
_UUID = rf"(?<!{_HEX}){_HEX}{{8}}-{_HEX}{{4}}-{_HEX}{{4}}-{_HEX}{{4}}-{_HEX}{{12}}(?!{_HEX})"
_PROTECTED_IDENTIFIER = re.compile(f"{_USER_HASH}|{_UUID}")

_PHONE_NUMBER = re.compile(r"\+?\d[\d\s-]{8,14}\d")
_BEARER_TOKEN = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
_OPAQUE_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,}")

_KEYS_NOT_SCANNED = frozenset({"timestamp", "level", "env"})
"""Keys our own processors add; their values are never personal data."""


def configure_logging(level: str, *, environment: str) -> None:
    """Install the processor chain. Called once by the app factory (and the worker, from S4)."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_environment(environment),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            redact_personal_data,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> FilteringBoundLogger:
    """The only way code outside app/core gets a logger, so redaction can't be bypassed."""
    return cast(FilteringBoundLogger, structlog.get_logger(name))


def redact_personal_data(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """structlog processor. Runs after the traceback is formatted and just before rendering."""
    del logger, method_name  # required by the processor signature; not needed here
    redacted: EventDict = {}
    for key, value in event_dict.items():
        if key in _KEYS_NOT_SCANNED:
            redacted[key] = value
        else:
            redacted[key] = redact_value(key, value)
    return redacted


def redact_value(key: str | None, value: object) -> object:
    """Redact one value found under `key` (None for list items), recursing into containers."""
    if key is not None and key.lower() in DENIED_KEYS:
        return REDACTED
    if isinstance(value, SecretStr):
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            str(item_key): redact_value(str(item_key), item) for item_key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [redact_value(None, item) for item in value]
    return value


def redact_text(text: str) -> str:
    """Replace phone numbers, bearer tokens and opaque tokens, leaving logged identifiers intact."""
    pieces: list[str] = []
    position = 0
    for identifier in _PROTECTED_IDENTIFIER.finditer(text):
        pieces.append(_redact_unprotected(text[position : identifier.start()]))
        pieces.append(identifier.group())
        position = identifier.end()
    pieces.append(_redact_unprotected(text[position:]))
    return "".join(pieces)


def _redact_unprotected(text: str) -> str:
    without_bearer = _BEARER_TOKEN.sub("Bearer " + REDACTED, text)
    without_phones = _PHONE_NUMBER.sub("[phone]", without_bearer)
    return _OPAQUE_TOKEN.sub("[token]", without_phones)


def _add_environment(environment: str) -> structlog.typing.Processor:
    def add_environment(
        logger: WrappedLogger, method_name: str, event_dict: EventDict
    ) -> EventDict:
        del logger, method_name
        event_dict["env"] = environment
        return event_dict

    return add_environment
