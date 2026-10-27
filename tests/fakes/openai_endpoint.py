"""A scripted OpenAI-compatible endpoint behind a real AsyncOpenAI client.

The openai SDK sends through its own `httpx2`, so respx can't see its calls; a MockTransport on
the client's own HTTP layer can. Each request takes the next scripted reply (the last repeats).
"""

import json
from collections.abc import Mapping, Sequence

import httpx2
from openai import AsyncOpenAI

from app.core.types import JsonValue

BASE_URL = "https://openai-compatible.test/v1"

type ScriptedReply = httpx2.Response | httpx2.TransportError


class ScriptedEndpoint:
    def __init__(self, replies: Sequence[ScriptedReply]) -> None:
        self._replies = list(replies)
        self.bodies: list[dict[str, JsonValue]] = []

    @property
    def call_count(self) -> int:
        return len(self.bodies)

    def client(self) -> AsyncOpenAI:
        transport = httpx2.MockTransport(self._handle)
        return AsyncOpenAI(
            base_url=BASE_URL,
            api_key="key-for-tests",
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=transport),
        )

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        body: dict[str, JsonValue] = json.loads(request.content)
        self.bodies.append(body)
        reply = self._replies[min(len(self.bodies) - 1, len(self._replies) - 1)]
        if isinstance(reply, httpx2.TransportError):
            raise reply
        return reply


def chat_completion(
    content: str | None,
    *,
    finish_reason: str = "stop",
    prompt_tokens: int = 1000,
    completion_tokens: int = 100,
) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish_reason,
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "prompt_tokens_details": {"cached_tokens": 0},
            },
        },
    )


def api_error(status: int, headers: Mapping[str, str] | None = None) -> httpx2.Response:
    return httpx2.Response(status, json={"error": {"message": "nope"}}, headers=headers)
