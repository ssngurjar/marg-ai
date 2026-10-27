"""MetaModelApiLanguageModel: Muse Spark through Chat Completions, strict JSON (s05 §4.1, ADR 0007).

One `generate` call = transport attempts under the shared RetryPolicy, then validation. A reply
that fails the schema or the request's semantic check gets exactly one repair turn, worded as
s05 §4.1 specifies; a second failure raises ProviderResponseInvalid (not retryable). Token usage
from both attempts is summed into one StepUsage.
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import ClassVar, Final

from openai import APIError, AsyncOpenAI
from openai.types.chat import ChatCompletion
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam
from openai.types.shared_params.response_format_json_schema import ResponseFormatJSONSchema
from pydantic import BaseModel, SecretStr, ValidationError

from app.core.clock import Clock
from app.core.errors import ProviderResponseInvalid
from app.core.strict_json_schema import JsonObject, StrictJsonSchema
from app.domain.models.usage import StepUsage
from app.providers.http import RetryPolicy
from app.providers.llm.model_pricing import ModelPricing
from app.providers.openai_error_mapper import OpenAiErrorMapper
from app.providers.ports import GenerationRequest, GenerationResult

PROVIDER: Final = "meta_model_api"


@dataclass(frozen=True, slots=True)
class ModelApiConfig:
    base_url: str
    api_key: SecretStr
    timeout_s: float  # one transport attempt; the orchestrator also bounds the whole step


@dataclass(frozen=True, slots=True)
class _Completion:
    content: str
    prompt_tokens: int
    cached_tokens: int
    completion_tokens: int


class MetaModelApiLanguageModel:
    """Satisfies `LanguageModel`."""

    REPAIR_MESSAGE: ClassVar[str] = (
        "Your previous reply did not pass validation. Errors: {errors}. "
        "Reply again with only the corrected JSON object."
    )

    def __init__(
        self,
        *,
        config: ModelApiConfig,
        retry: RetryPolicy,
        clock: Clock,
        client: AsyncOpenAI | None = None,
    ) -> None:
        """`client` is for tests; normally the adapter creates and owns its own."""
        self._client = client or AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key.get_secret_value(),
            timeout=config.timeout_s,
            max_retries=0,  # RetryPolicy owns retries
        )
        self._timeout_s = config.timeout_s
        self._retry = retry
        self._clock = clock

    async def aclose(self) -> None:
        await self._client.close()

    async def generate[OutputT: BaseModel](
        self, request: GenerationRequest[OutputT]
    ) -> GenerationResult[OutputT]:
        started = time.perf_counter()
        schema = StrictJsonSchema.from_model(request.output_type)
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": request.prompt.system},
            {"role": "user", "content": request.prompt.user},
        ]
        first = await self._complete_with_retries(request, schema, messages)
        completions = [first]
        output, problems = self._validate(request, first.content)
        if output is None:
            repair_messages: list[ChatCompletionMessageParam] = [
                *messages,
                {"role": "assistant", "content": first.content},
                {"role": "user", "content": self.REPAIR_MESSAGE.format(errors="; ".join(problems))},
            ]
            second = await self._complete_with_retries(request, schema, repair_messages)
            completions.append(second)
            output, problems = self._validate(request, second.content)
            if output is None:
                raise ProviderResponseInvalid(
                    f"{request.prompt.prompt_id}: reply failed validation after one repair "
                    f"({len(problems)} problem(s))",
                    provider=PROVIDER,
                    retryable=False,
                )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return GenerationResult(
            output=output, usage=self._usage(request.model, completions), latency_ms=latency_ms
        )

    async def _complete_with_retries[OutputT: BaseModel](
        self,
        request: GenerationRequest[OutputT],
        schema: JsonObject,
        messages: list[ChatCompletionMessageParam],
    ) -> _Completion:
        deadline = self._clock.now() + timedelta(seconds=self._timeout_s)
        return await self._retry.run(
            lambda: self._complete_once(request, schema, messages), deadline=deadline
        )

    async def _complete_once[OutputT: BaseModel](
        self,
        request: GenerationRequest[OutputT],
        schema: JsonObject,
        messages: list[ChatCompletionMessageParam],
    ) -> _Completion:
        try:
            completion = await self._client.chat.completions.create(
                model=request.model,
                messages=messages,
                response_format=self._response_format(request.prompt.prompt_id, schema),
                reasoning_effort=request.reasoning_effort,
                max_tokens=request.max_output_tokens,
            )
        except APIError as exc:
            raise OpenAiErrorMapper.map(
                exc, label=request.prompt.prompt_id, provider=PROVIDER
            ) from exc
        return self._read(request, completion)

    def _read[OutputT: BaseModel](
        self, request: GenerationRequest[OutputT], completion: ChatCompletion
    ) -> _Completion:
        prompt_id = request.prompt.prompt_id
        if not completion.choices:
            raise ProviderResponseInvalid(f"{prompt_id}: no choices returned", provider=PROVIDER)
        choice = completion.choices[0]
        if choice.finish_reason == "length":
            raise ProviderResponseInvalid(
                f"{prompt_id}: output truncated at max_tokens={request.max_output_tokens}",
                provider=PROVIDER,
                retryable=False,  # the same budget would truncate again
            )
        content = choice.message.content
        if not content:
            raise ProviderResponseInvalid(f"{prompt_id}: empty content", provider=PROVIDER)
        usage = completion.usage
        cached = 0
        if usage is not None and usage.prompt_tokens_details is not None:
            cached = usage.prompt_tokens_details.cached_tokens or 0
        return _Completion(
            content=content,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            cached_tokens=cached,
            completion_tokens=usage.completion_tokens if usage else 0,
        )

    @staticmethod
    def _response_format(name: str, schema: JsonObject) -> ResponseFormatJSONSchema:
        return {
            "type": "json_schema",
            "json_schema": {"name": name, "schema": dict(schema), "strict": True},
        }

    @staticmethod
    def _validate[OutputT: BaseModel](
        request: GenerationRequest[OutputT], content: str
    ) -> tuple[OutputT | None, list[str]]:
        """The validated output, or None and the problems to send back in the repair turn.

        Schema errors carry only `loc` and `msg`, never the input, so generated text isn't
        echoed into logs. Semantic problems are fixed-vocabulary strings from the checker.
        """
        try:
            output = request.output_type.model_validate_json(content)
        except ValidationError as exc:
            errors = exc.errors(include_input=False, include_url=False)
            return None, [
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in errors
            ]
        if request.semantic_check is not None:
            problems = request.semantic_check(output)
            if problems:
                return None, problems
        return output, []

    @staticmethod
    def _usage(model: str, completions: Sequence[_Completion]) -> StepUsage:
        prompt_tokens = sum(completion.prompt_tokens for completion in completions)
        cached_tokens = sum(completion.cached_tokens for completion in completions)
        completion_tokens = sum(completion.completion_tokens for completion in completions)
        return StepUsage(
            provider=PROVIDER,
            model=model,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            audio_seconds=None,
            cost_usd=ModelPricing.cost_of(model, prompt_tokens, cached_tokens, completion_tokens),
        )
