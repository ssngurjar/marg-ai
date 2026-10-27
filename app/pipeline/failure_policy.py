"""FailurePolicy: what a failed step becomes (s05 §4.5 "StepFailure → reply"; contracts §4)."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import ClassVar

from app.core.errors import (
    ProviderError,
    ProviderRateLimited,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
    SafetyUnavailable,
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
        if isinstance(error, TimeoutError | ProviderTimeout):
            return FailureKind.TIMEOUT
        if isinstance(error, ProviderRateLimited):
            return FailureKind.RATE_LIMITED
        if isinstance(error, ProviderUnavailable | SafetyUnavailable):
            return FailureKind.UNAVAILABLE
        if isinstance(error, ProviderResponseInvalid):
            return FailureKind.INVALID_RESPONSE
        return FailureKind.INTERNAL

    @staticmethod
    def is_retryable(error: BaseException) -> bool:
        if isinstance(error, ProviderError):
            return error.retryable
        return isinstance(error, TimeoutError)

    @staticmethod
    def reply_for(step: StepName) -> FixedReplyKind:
        return FailurePolicy.REPLY_FOR_FAILED_STEP[step]
