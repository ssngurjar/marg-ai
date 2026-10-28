"""Fake image providers: an ImageGenerator (a tiny valid PNG, or a scripted error; records the
prompts it got) and an ImageSegmenter (scripted counts per phrase)."""

import base64
from collections.abc import Mapping, Sequence
from decimal import Decimal

from app.core.errors import MargError
from app.domain.models.message import ImageClip
from app.domain.models.photo import ObjectCount
from app.domain.models.usage import StepUsage

# A 1x1 transparent PNG
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)
IMAGE_USAGE = StepUsage(
    provider="meta_model_api",
    model="muse-image-1.0",
    input_tokens=None,
    output_tokens=None,
    audio_seconds=None,
    cost_usd=Decimal("0.01"),
)


class FakeImageGenerator:
    """Satisfies `ImageGenerator`."""

    def __init__(self, error: MargError | None = None) -> None:
        self.prompts: list[str] = []
        self._error = error

    async def generate(self, prompt: str) -> tuple[ImageClip, StepUsage]:
        self.prompts.append(prompt)
        if self._error is not None:
            raise self._error
        return ImageClip(data=TINY_PNG, mime_type="image/png"), IMAGE_USAGE


SEGMENT_USAGE = StepUsage(
    provider="meta_model_api",
    model="sam-3.1",
    input_tokens=None,
    output_tokens=None,
    audio_seconds=None,
    cost_usd=Decimal("0.0025"),
)


class FakeImageSegmenter:
    """Satisfies `ImageSegmenter`. `found` is how many of each phrase are in every photo (0 when
    not listed); `error` is raised for calls that ask for any phrase in `fail_on` (all when
    empty). Records every call's phrases."""

    def __init__(
        self,
        found: Mapping[str, int] | None = None,
        error: MargError | None = None,
        *,
        fail_on: frozenset[str] = frozenset(),
    ) -> None:
        self.calls: list[list[str]] = []
        self.images: list[ImageClip] = []
        self._found = dict(found or {})
        self._error = error
        self._fail_on = fail_on

    async def count(
        self, image: ImageClip, phrases: Sequence[str]
    ) -> tuple[list[ObjectCount], StepUsage]:
        self.calls.append(list(phrases))
        self.images.append(image)
        if self._error is not None and (not self._fail_on or self._fail_on & set(phrases)):
            raise self._error
        counts = [
            ObjectCount(phrase=phrase, count=self._found.get(phrase, 0)) for phrase in phrases
        ]
        return counts, SEGMENT_USAGE
