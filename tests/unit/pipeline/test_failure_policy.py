"""FailurePolicy: a failed step's kind, retryability and fallback reply (s05 §4.5)."""

import pytest

from app.core.errors import (
    ConfigError,
    MediaTooLarge,
    MediaUnsupported,
    ProviderError,
    ProviderRateLimited,
    ProviderRejected,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
    SafetyUnavailable,
    TranscodeFailed,
    TranscodeTimeout,
    TtsTextInvalid,
)
from app.domain.enums import FailureKind, FixedReplyKind, StepName
from app.pipeline.failure_policy import FailurePolicy

pytestmark = pytest.mark.unit

P = "meta_model_api"


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (TimeoutError(), FailureKind.TIMEOUT),
        (ProviderTimeout("t", provider=P), FailureKind.TIMEOUT),
        (ProviderRateLimited("r", provider=P, retry_after=2.0), FailureKind.RATE_LIMITED),
        (ProviderUnavailable("u", provider=P), FailureKind.UNAVAILABLE),
        (SafetyUnavailable("llama_guard down"), FailureKind.UNAVAILABLE),
        (ProviderResponseInvalid("bad", provider=P), FailureKind.INVALID_RESPONSE),
        (ProviderRejected("400", provider=P), FailureKind.INTERNAL),
        (ConfigError("bad prompt"), FailureKind.INTERNAL),
        (MediaTooLarge("9 MB"), FailureKind.UNSUPPORTED_INPUT),
        (MediaUnsupported("no media"), FailureKind.UNSUPPORTED_INPUT),
        (TranscodeFailed("ffmpeg exited 1"), FailureKind.UNSUPPORTED_INPUT),
        (TranscodeTimeout("ffmpeg timed out"), FailureKind.TIMEOUT),
        (TtsTextInvalid("latin letters"), FailureKind.INVALID_RESPONSE),
    ],
)
def test_each_error_is_recorded_as_its_kind(error: BaseException, kind: FailureKind) -> None:
    assert FailurePolicy.kind_of(error) is kind


@pytest.mark.parametrize(
    "error", [TimeoutError(), ProviderUnavailable("u", provider=P)], ids=["timeout", "unavailable"]
)
def test_transient_failures_are_retryable(error: BaseException) -> None:
    assert FailurePolicy.is_retryable(error)


@pytest.mark.parametrize(
    "error",
    [
        ProviderRejected("400", provider=P),
        ProviderResponseInvalid("after repair", provider=P, retryable=False),
        SafetyUnavailable("down"),
    ],
    ids=["rejected", "invalid-after-repair", "safety-unavailable"],
)
def test_permanent_failures_are_not_retryable(error: BaseException) -> None:
    assert not FailurePolicy.is_retryable(error)


def test_a_failed_safety_check_always_answers_with_the_holding_reply() -> None:
    assert FailurePolicy.reply_for(StepName.SAFETY_IN) is FixedReplyKind.HOLDING
    assert FailurePolicy.reply_for(StepName.SAFETY_OUT) is FixedReplyKind.HOLDING


@pytest.mark.parametrize("step", [StepName.ROUTE, StepName.GENERATE, StepName.TRANSLATE])
def test_other_failed_steps_ask_to_try_again_later(step: StepName) -> None:
    assert FailurePolicy.reply_for(step) is FixedReplyKind.TRY_AGAIN_LATER


def test_unlisted_provider_error_subclass_is_internal() -> None:
    assert FailurePolicy.kind_of(ProviderError("x", provider=P, retryable=False)) is (
        FailureKind.INTERNAL
    )


@pytest.mark.parametrize(
    ("error", "reply"),
    [
        (MediaTooLarge("9 MB"), FixedReplyKind.UNSUPPORTED_MEDIA),
        (MediaUnsupported("no media"), FixedReplyKind.UNSUPPORTED_MEDIA),
        (TranscodeFailed("ffmpeg exited 1"), FixedReplyKind.UNSUPPORTED_MEDIA),
        (TranscodeTimeout("ffmpeg timed out"), FixedReplyKind.REPEAT_PLEASE),
        (ProviderUnavailable("u", provider=P), FixedReplyKind.REPEAT_PLEASE),
        (TimeoutError(), FixedReplyKind.REPEAT_PLEASE),
    ],
)
def test_a_voice_note_we_cant_read_is_unsupported_and_anything_else_asks_again(
    error: BaseException, reply: FixedReplyKind
) -> None:
    assert FailurePolicy.reply_for_voice_note(error) is reply
