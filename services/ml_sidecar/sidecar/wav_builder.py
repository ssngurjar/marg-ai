"""WavBuilder: a reply's spoken sentences as one 16-bit mono WAV (s06 §4.9)."""

import io
import wave
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

import numpy as np

from sidecar.speech_engine import Waveform


@dataclass(frozen=True, slots=True)
class WavAudio:
    wav_bytes: bytes
    duration_ms: int


class WavBuilder:
    SILENCE_BETWEEN_SENTENCES_S: ClassVar[float] = 0.25

    @staticmethod
    def join(pieces: Sequence[Waveform], sampling_rate: int) -> WavAudio:
        """The pieces with a short silence between them, clipped to [-1, 1]."""
        if not pieces:
            raise ValueError("a WAV needs at least one sentence of audio")
        silence_samples = int(sampling_rate * WavBuilder.SILENCE_BETWEEN_SENTENCES_S)
        silence = np.zeros(silence_samples, dtype=np.float32)
        joined: list[Waveform] = []
        for index, piece in enumerate(pieces):
            if index:
                joined.append(silence)
            joined.append(piece)
        audio = np.concatenate(joined)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sampling_rate)
            wav_file.writeframes(pcm.tobytes())
        return WavAudio(wav_bytes=buffer.getvalue(), duration_ms=len(pcm) * 1000 // sampling_rate)
