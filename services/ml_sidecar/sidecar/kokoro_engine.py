"""KokoroEngine: Kokoro-82M (Apache 2.0) speaking Hindi, Hinglish and English on a CPU.

Chosen over MMS-TTS on 2026-10-29 (s06 decisions log): clearer in a transcription check and
about 1 s for 8 s of speech on a laptop CPU.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import ClassVar, Protocol

import numpy as np
import torch

from sidecar.speech_engine import Engine, SpeechFailed, Voice, Waveform


class KokoroResult(Protocol):
    @property
    def audio(self) -> torch.Tensor | None: ...


class KokoroPipeline(Protocol):
    """The part of `kokoro.KPipeline` Marg uses (kokoro ships no type information)."""

    def __call__(
        self, text: str, *, voice: torch.Tensor, speed: float
    ) -> Iterable[KokoroResult]: ...

    def load_voice(self, voice: str) -> torch.Tensor: ...


@dataclass(frozen=True, slots=True)
class KokoroVoice:
    language_code: str  # kokoro's code: "h" Hindi, "a" American English
    voice_names: str  # comma-separated names are blended half and half
    speed: float


class KokoroEngine:
    name: Engine = "kokoro"
    MODEL: ClassVar[str] = "hexgrad/Kokoro-82M"
    SAMPLING_RATE: ClassVar[int] = 24000
    # The owner's pick by ear (spike option 5): two female Hindi voices blended, a little faster,
    # sound livelier than either alone. English keeps af_heart at normal speed.
    VOICES: ClassVar[dict[Voice, KokoroVoice]] = {
        "hin": KokoroVoice(language_code="h", voice_names="hf_alpha,hf_beta", speed=1.1),
        "eng": KokoroVoice(language_code="a", voice_names="af_heart", speed=1.0),
    }

    def __init__(self, pipelines: Mapping[Voice, KokoroPipeline]) -> None:
        self._pipelines = dict(pipelines)
        self._voice_packs = {
            voice: self._pipelines[voice].load_voice(setting.voice_names)
            for voice, setting in self.VOICES.items()
        }
        self.sampling_rate: int = self.SAMPLING_RATE

    @classmethod
    def load(cls, device: str) -> "KokoroEngine":
        # kokoro ships no type information; KokoroPipeline above types what is used.
        from kokoro import KModel, KPipeline  # type: ignore[import-untyped]  # noqa: PLC0415  # loaded only when this engine runs

        model = KModel(repo_id=cls.MODEL).to(device).eval()
        pipelines: dict[Voice, KokoroPipeline] = {}
        for voice, setting in cls.VOICES.items():
            pipelines[voice] = KPipeline(
                lang_code=setting.language_code, repo_id=cls.MODEL, model=model
            )
        return cls(pipelines)

    def models_loaded(self) -> list[str]:
        return [self.MODEL]

    def speak(self, sentence: str, voice: Voice) -> Waveform:
        setting = self.VOICES[voice]
        pieces: list[Waveform] = []
        for result in self._pipelines[voice](
            sentence, voice=self._voice_packs[voice], speed=setting.speed
        ):
            if result.audio is None:
                raise SpeechFailed(f"kokoro returned a chunk without audio for a {voice} sentence")
            pieces.append(result.audio.float().cpu().numpy().astype(np.float32))
        if not pieces:
            raise SpeechFailed(f"kokoro returned no audio for a {voice} sentence")
        return np.concatenate(pieces)
