"""FailurePolicy: what a failed step becomes (s05 §4.5 "StepFailure → reply"; contracts §4)."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import ClassVar

from app.core.errors import (
    MediaError,
    ProviderError,
    ProviderRateLimited,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
    SafetyUnavailable,
    TranscodeTimeout,
    TtsTextInvalid,
)
from app.domain.enums import FailureKind, FixedReplyKind, StepName


class FailurePolicy:
    REPLY_FOR_FAILED_STEP: ClassVar[Mapping[StepName, FixedReplyKind]] = MappingProxyType(
        {
            StepName.SAFETY_IN: FixedReplyKind.HOLDING,  # fail closed
            StepName.ROUTE: FixedReplyKind.TRY_AGAIN_LATER,
            StepName.GENERATE: FixedReplyKind.TRY_AGAIN_LATER,
            StepName.TRANSLATE: FixedReplyKind.TRY_AGAIN_LATER,
            StepName.SAFETY_OUT: FixedReplyKind.HOLDING,  # fail closed
        }
    )

    @staticmethod
    def kind_of(error: BaseException) -> FailureKind:
        """The FailureKind recorded for an exception a step raised."""
        if isinstance(error, TimeoutError | ProviderTimeout | TranscodeTimeout):
            return FailureKind.TIMEOUT
        if isinstance(error, ProviderRateLimited):
            return FailureKind.RATE_LIMITED
        if isinstance(error, ProviderUnavailable | SafetyUnavailable):
            return FailureKind.UNAVAILABLE
        if isinstance(error, ProviderResponseInvalid | TtsTextInvalid):
            return FailureKind.INVALID_RESPONSE
        if isinstance(error, MediaError):  # too large, unsupported, or ffmpeg couldn't read it
            return FailureKind.UNSUPPORTED_INPUT
        return FailureKind.INTERNAL

    @staticmethod
    def is_retryable(error: BaseException) -> bool:
        if isinstance(error, ProviderError):
            return error.retryable
        return isinstance(error, TimeoutError)

    @staticmethod
    def reply_for_voice_note(error: BaseException) -> FixedReplyKind:
        """A voice note we couldn't hear (s06 §8): audio we can't read is UNSUPPORTED_MEDIA;
        anything that might work a second time asks the user to send it again."""
        if isinstance(error, MediaError) and not isinstance(error, TranscodeTimeout):
            return FixedReplyKind.UNSUPPORTED_MEDIA
        return FixedReplyKind.REPEAT_PLEASE

    @staticmethod
    def reply_for(step: StepName) -> FixedReplyKind:
        return FailurePolicy.REPLY_FOR_FAILED_STEP[step]
