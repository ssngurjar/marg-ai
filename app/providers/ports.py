"""Protocols the pipeline and layers depend on (contracts.md §3).

Each step adds the ports it introduces. Adapters implement them; tests use fakes from tests/fakes.
The `Clock` protocol lives in app/core/clock.py (core infrastructure, importable by every layer).
"""

from collections.abc import Callable
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, SecretStr

from app.core.types import ReasoningEffort
from app.domain.enums import Channel
from app.domain.models.message import AudioClip, ImageClip
from app.domain.models.reply import OutboundPart
from app.domain.models.safety import SafetyVerdict
from app.domain.models.usage import StepUsage


class ChannelAddress(BaseModel):
    """Where a part goes. Decrypted only inside the sender, never logged."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: Channel
    address: SecretStr  # wa_id digits for WhatsApp; user_hash for web


class DeliveryReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_message_id: str | None  # wamid for WhatsApp; None for web
    sent_at: datetime


class ChannelSender(Protocol):
    channel: Channel

    async def send(
        self,
        part: OutboundPart,
        recipient: ChannelAddress,
        audio: AudioClip | None = None,
        image: ImageClip | None = None,
    ) -> DeliveryReceipt: ...

    async def acknowledge(self, external_id: str) -> None:
        """WhatsApp: mark read and show "typing…". Web: nothing."""
        ...


# --- language model (S5) ----------------------------------------------------------------------


class RenderedPrompt(BaseModel):
    """A prompt ready to send. User text appears only inside registry-wrapped slots."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_id: str  # e.g. "parent_answer"
    prompt_version: str  # from the template's frontmatter
    system: str
    user: str


class GenerationRequest[OutputT: BaseModel](BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    prompt: RenderedPrompt
    output_type: type[OutputT]  # a strict JSON schema: no defaults, every field required
    model: str  # from settings, never a literal in a layer
    reasoning_effort: ReasoningEffort
    max_output_tokens: int  # includes reasoning tokens, which bill at the output rate
    semantic_check: Callable[[OutputT], list[str]] | None  # problems → one repair retry


class GenerationResult[OutputT: BaseModel](BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    output: OutputT
    usage: StepUsage
    latency_ms: int


class LanguageModel(Protocol):
    async def generate[OutputT: BaseModel](
        self, request: GenerationRequest[OutputT]
    ) -> GenerationResult[OutputT]: ...


# --- safety classifier (S5, pulled forward from S7) ------------------------------------------


class SafetyRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    speaker: Literal["user", "assistant"]
    text: str
    prior_user_text: str | None  # required for assistant checks
    image: ImageClip | None = None  # photos in, khoj cards out (C6, C7)


class SafetyClassifier(Protocol):
    async def classify(self, request: SafetyRequest) -> tuple[SafetyVerdict, StepUsage]: ...
