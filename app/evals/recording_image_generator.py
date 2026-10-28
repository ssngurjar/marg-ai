"""RecordingImageGenerator: khoj-card picture stand-in for `marg eval` (s15 §4.2).

A card's picture costs money per image and isn't what a scorecard judges, so by default the
eval returns a fixed 1x1 PNG and keeps the prompt (so "no nickname or parent's words in the
image prompt" can be checked). `--live-images` uses Muse Image. Never wired into production.
"""

import base64
from collections import defaultdict
from typing import Final

from app.domain.models.message import ImageClip
from app.domain.models.usage import StepUsage
from app.evals.eval_context import EvalContext
from app.evals.recording_synthesizer import NO_COST

ONE_PIXEL_PNG: Final = ImageClip(
    data=base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAwS2OUAAAAABJRU5ErkJggg=="
    ),
    mime_type="image/png",
)


class RecordingImageGenerator:
    def __init__(self) -> None:
        self._prompts: defaultdict[str, list[str]] = defaultdict(list)

    async def generate(self, prompt: str) -> tuple[ImageClip, StepUsage]:
        self._prompts[EvalContext.current()].append(prompt)
        return ONE_PIXEL_PNG, NO_COST

    def prompts_in(self, turn_key: str) -> list[str]:
        return self._prompts.pop(turn_key, [])
