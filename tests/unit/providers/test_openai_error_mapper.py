"""OpenAiErrorMapper.retry_after: only a finite, numeric header counts."""

import httpx2
import pytest
from openai import RateLimitError

from app.providers.openai_error_mapper import OpenAiErrorMapper

pytestmark = pytest.mark.unit


def rate_limited(headers: dict[str, str]) -> RateLimitError:
    request = httpx2.Request("POST", "https://model-api.test/v1/chat/completions")
    response = httpx2.Response(429, headers=headers, request=request)
    return RateLimitError("rate limited", response=response, body=None)


@pytest.mark.parametrize(
    ("header", "seconds"),
    [("2", 2.0), ("0.5", 0.5), ("0", 0.0), ("-3", 0.0)],
)
def test_a_numeric_retry_after_is_used(header: str, seconds: float) -> None:
    assert OpenAiErrorMapper.retry_after(rate_limited({"retry-after": header})) == seconds


@pytest.mark.parametrize(
    "header", ["", "soon", "Wed, 21 Oct 2026 07:28:00 GMT", "nan", "inf", "-inf"]
)
def test_anything_else_is_ignored(header: str) -> None:
    assert OpenAiErrorMapper.retry_after(rate_limited({"retry-after": header})) is None


def test_a_missing_header_is_none() -> None:
    assert OpenAiErrorMapper.retry_after(rate_limited({})) is None
