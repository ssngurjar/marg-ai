"""Every exception raised by Marg.ai code (contracts.md §4).

Messages name what failed (provider, step, table, field) and never contain user content.
"""


class MargError(Exception):
    """Base for every exception raised by Marg.ai code."""


class ConfigError(MargError):
    """Settings are missing or invalid at startup."""


class ProviderError(MargError):
    """An external provider call failed. `retryable` tells the retry policy what to do."""

    def __init__(self, message: str, *, provider: str, retryable: bool) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class ProviderTimeout(ProviderError):
    """The provider didn't answer in time. Always retryable."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message, provider=provider, retryable=True)


class ProviderRateLimited(ProviderError):
    """The provider returned 429. Always retryable, after `retry_after` seconds if given."""

    def __init__(self, message: str, *, provider: str, retry_after: float | None) -> None:
        super().__init__(message, provider=provider, retryable=True)
        self.retry_after = retry_after


class ProviderUnavailable(ProviderError):
    """A 5xx or connection failure. Always retryable."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message, provider=provider, retryable=True)


class ProviderRejected(ProviderError):
    """A 4xx other than 429: our request was wrong or unauthorised. Never retried."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message, provider=provider, retryable=False)


class ProviderResponseInvalid(ProviderError):
    """The response couldn't be parsed or didn't match the schema.

    Retryable by default (the retry policy retries it once); pass `retryable=False` when a retry
    can't help, e.g. output truncated at the token limit.
    """

    def __init__(self, message: str, *, provider: str, retryable: bool = True) -> None:
        super().__init__(message, provider=provider, retryable=retryable)


class SafetyUnavailable(MargError):
    """The safety classifier failed after retries. The pipeline fails closed."""


class MediaError(MargError):
    """Base for media problems: audio or images we can't use."""


class MediaTooLarge(MediaError):
    """The media is over the size cap."""


class MediaUnsupported(MediaError):
    """The media type isn't one we accept."""


class TranscodeFailed(MediaError):
    """ffmpeg failed or timed out."""


class TtsTextInvalid(MediaError):
    """The text prepared for speech synthesis broke a rule (script, length)."""


class ChannelError(MargError):
    """Base for WhatsApp and web channel problems."""


class SignatureInvalid(ChannelError):
    """A webhook signature didn't verify. The request is rejected with 401."""


class PayloadInvalid(ChannelError):
    """An authentic payload couldn't be parsed."""


class InvalidAddressCiphertext(ChannelError):
    """A stored address couldn't be decrypted for this user."""


class DeliveryFailed(ChannelError):
    """Sending an outbox part failed after retries."""


class DomainError(MargError):
    """Base for broken domain rules."""


class InvalidTransition(DomainError):
    """An event isn't allowed in the conversation's current state."""


class InvalidProfileValue(DomainError):
    """A profile or learner value is out of range (e.g. grade 13)."""


class StoreError(MargError):
    """Base for database problems."""


class LeaseLost(StoreError):
    """Another worker owns the user, or the expected state changed. Abandon without writing."""


class NotFound(StoreError):
    """A row that must exist doesn't."""


class CorpusValidationError(MargError):
    """A corpus, curriculum or activity catalogue file is invalid."""


class GoldenCaseInvalid(MargError):
    """An eval case file is invalid."""


class LinkInvalid(MargError):
    """A signed dashboard link was rejected."""


class BudgetExceeded(MargError):
    """A daily cost cap has been reached."""


class RateLimited(MargError):
    """One of our own rate limits has been reached."""
