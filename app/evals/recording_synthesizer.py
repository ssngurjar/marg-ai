"""RecordingSynthesizer: text-to-speech stand-in for `marg eval` (s15 §4.2).

Replies are judged on what they say, not on audio, so by default the eval doesn't call the
voice server: this keeps the exact text the pipeline sent to TTS (what the "nothing a voice
can't read" check needs) and returns 100 ms of silence. `--with-tts` uses the real voice server.
It is part of the eval harness and never wired into production.
"""

from collections import defaultdict
from decimal import Decimal
from typing import Final

from app.domain.enums import Language
from app.domain.models.message import AudioClip
from app.domain.models.usage import StepUsage
from app.evals.eval_context import EvalContext

SILENCE: Final = AudioClip(data=b"\x00" * 1600, mime_type="audio/wav", duration_ms=100)
NO_COST: Final = StepUsage(
    provider="eval_recording",
    model=None,
    input_tokens=None,
    output_tokens=None,
    audio_seconds=None,
    cost_usd=Decimal(0),
)


class RecordingSynthesizer:
    def __init__(self) -> None:
        self._spoken: defaultdict[str, list[str]] = defaultdict(list)

    async def synthesize(self, text: str, language: Language) -> tuple[AudioClip, StepUsage]:
        self._spoken[EvalContext.current()].append(text)
        return SILENCE, NO_COST

    def spoken_in(self, turn_key: str) -> list[str]:
        """Every text the turn sent to TTS, in order (removed once read)."""
        return self._spoken.pop(turn_key, [])
