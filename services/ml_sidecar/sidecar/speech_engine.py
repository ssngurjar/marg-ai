"""SpeechEngine: the port every text-to-speech model plugs into (s06 §4.7).

Marg uses Kokoro-82M. Another model plugs in as a class satisfying SpeechEngine, a name added
to `Engine`, and an entry in `server.ENGINES`; the app's `TTS_ENGINE` setting names it.
"""

from typing import Literal, Protocol

import numpy as np
import numpy.typing as npt

type Engine = Literal["kokoro"]
type Voice = Literal["hin", "eng"]
type Waveform = npt.NDArray[np.float32]

KNOWN_ENGINES: dict[str, Engine] = {"kokoro": "kokoro"}


class SpeechFailed(RuntimeError):
    """The model returned no audio for a sentence it accepted."""


class SpeechEngine(Protocol):
    @property
    def name(self) -> Engine: ...

    @property
    def sampling_rate(self) -> int: ...

    def models_loaded(self) -> list[str]: ...

    def speak(self, sentence: str, voice: Voice) -> Waveform: ...
