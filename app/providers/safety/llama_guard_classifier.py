"""LlamaGuardClassifier: Llama Guard 4 on an OpenAI-compatible host (s07 §4.3, contracts §3).

The host applies Llama Guard's own chat template. A user check sends the user's turn; a reply
check sends the user's turn and our reply, and Llama Guard classifies the last turn. The
decision here is only "flagged or not": the safety gate maps categories to ALLOW / BLOCK / CRISIS
separately for input and output (s07 §4.4).
"""

import base64
from dataclasses import dataclass
from datetime import timedelta

from openai import APIError, AsyncOpenAI
from openai.types.chat import ChatCompletion
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam
from pydantic import SecretStr

from app.core.clock import Clock
from app.core.errors import ProviderResponseInvalid
from app.domain.enums import SafetyDecision
from app.domain.models.safety import SafetyVerdict
from app.domain.models.usage import StepUsage
from app.providers.http import RetryPolicy
from app.providers.llm.model_pricing import ModelPricing
from app.providers.openai_error_mapper import OpenAiErrorMapper
from app.providers.ports import SafetyRequest
from app.providers.safety.llama_guard_output_parser import PROVIDER, LlamaGuardOutputParser

MAX_ANSWER_TOKENS = 20


@dataclass(frozen=True, slots=True)
class SafetyHostConfig:
    base_url: str
    api_key: SecretStr
    model: str
    timeout_s: float


class LlamaGuardClassifier:
    """Satisfies `SafetyClassifier`."""

    def __init__(
        self,
        *,
        config: SafetyHostConfig,
        retry: RetryPolicy,
        clock: Clock,
        client: AsyncOpenAI | None = None,
    ) -> None:
        """`client` is for tests; normally the classifier creates and owns its own."""
        self._client = client or AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key.get_secret_value(),
            timeout=config.timeout_s,
            max_retries=0,
        )
        self._model = config.model
        self._timeout_s = config.timeout_s
        self._retry = retry
        self._clock = clock

    async def aclose(self) -> None:
        await self._client.close()

    async def classify(self, request: SafetyRequest) -> tuple[SafetyVerdict, StepUsage]:
        messages = self._messages(request)
        deadline = self._clock.now() + timedelta(seconds=self._timeout_s)
        completion = await self._retry.run(lambda: self._complete(messages), deadline=deadline)
        categories = LlamaGuardOutputParser.parse(self._answer(completion))
        decision = SafetyDecision.BLOCK if categories else SafetyDecision.ALLOW
        verdict = SafetyVerdict(decision=decision, categories=categories, source="llama_guard")
        return verdict, self._usage(completion)

    def _messages(self, request: SafetyRequest) -> list[ChatCompletionMessageParam]:
        if request.image is not None:
            # Spike B: the host takes an image only together with a text part, in a user turn
            # (an image alone returns 500). The text is the caption that goes with it.
            encoded = base64.b64encode(request.image.data).decode("ascii")
            return [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": request.text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{request.image.mime_type};base64,{encoded}"
                            },
                        },
                    ],
                }
            ]
        if request.speaker == "user":
            return [{"role": "user", "content": request.text}]
        if request.prior_user_text is None:
            raise ValueError("a reply check needs the user's message it answers")
        return [
            {"role": "user", "content": request.prior_user_text},
            {"role": "assistant", "content": request.text},
        ]

    async def _complete(self, messages: list[ChatCompletionMessageParam]) -> ChatCompletion:
        try:
            return await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=MAX_ANSWER_TOKENS,
                temperature=0,
            )
        except APIError as exc:
            raise OpenAiErrorMapper.map(exc, label="llama guard", provider=PROVIDER) from exc

    @staticmethod
    def _answer(completion: ChatCompletion) -> str:
        if not completion.choices or not completion.choices[0].message.content:
            raise ProviderResponseInvalid("llama guard returned no answer", provider=PROVIDER)
        return completion.choices[0].message.content

    def _usage(self, completion: ChatCompletion) -> StepUsage:
        usage = completion.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        return StepUsage(
            provider=PROVIDER,
            model=self._model,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            audio_seconds=None,
            cost_usd=ModelPricing.cost_of(self._model, prompt_tokens, 0, completion_tokens),
        )
