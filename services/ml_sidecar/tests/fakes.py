"""Fake models for the sidecar's tests: no weights, no network."""

from collections.abc import Sequence

import numpy as np

from sidecar.speech_engine import Engine, SpeechFailed, Voice, Waveform


class FakeEngine:
    name: Engine = "kokoro"
    sampling_rate: int = 1000

    def __init__(self, *, fail: bool = False) -> None:
        self.spoken: list[tuple[str, Voice]] = []
        self._fail = fail

    def models_loaded(self) -> list[str]:
        return ["fake/speech"]

    def speak(self, sentence: str, voice: Voice) -> Waveform:
        if self._fail:
            raise SpeechFailed("fake engine made no audio")
        self.spoken.append((sentence, voice))
        return np.full(100, 0.5, dtype=np.float32)  # 0.1 s at 1000 Hz


class FakeEmbedder:
    dimensions: int = 3

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        return [[1.0, 0.0, 0.0] for _ in texts]
