"""SpeechEngine: the port every text-to-speech model plugs into (s06 §4.7).

Every model Marg calls must be a Meta model (organisers, 2026-10-29), so the one engine is
Meta's MMS-TTS. Another model plugs in as a class satisfying SpeechEngine, a name added to
`Engine` and `KNOWN_ENGINES`, and an entry in `server.ENGINES`; the app's `TTS_ENGINE` names it.
"""

from typing import Literal, Protocol

import numpy as np
import numpy.typing as npt

type Engine = Literal["mms"]
type Voice = Literal["hin", "eng"]
type Waveform = npt.NDArray[np.float32]

KNOWN_ENGINES: dict[str, Engine] = {"mms": "mms"}


class SpeechFailed(RuntimeError):
    """The model returned no audio for a sentence it accepted."""


class SpeechEngine(Protocol):
    @property
    def name(self) -> Engine: ...

    @property
    def sampling_rate(self) -> int: ...

    def models_loaded(self) -> list[str]: ...

    def speak(self, sentence: str, voice: Voice) -> Waveform: ...
