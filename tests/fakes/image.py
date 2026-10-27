"""A fake ImageGenerator: a tiny valid PNG, or a scripted error. Records the prompts it got."""

import base64
from decimal import Decimal

from app.core.errors import MargError
from app.domain.models.message import ImageClip
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
