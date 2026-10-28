"""WavBuilder: sentence audio joined into one 16-bit mono WAV."""

import io
import wave

import numpy as np
import pytest

from sidecar.wav_builder import WavBuilder

pytestmark = pytest.mark.unit


def frames(wav_bytes: bytes) -> list[int]:
    with wave.open(io.BytesIO(wav_bytes)) as wav_file:
        raw = wav_file.readframes(wav_file.getnframes())
    return np.frombuffer(raw, dtype=np.int16).tolist()


def test_one_sentence_has_no_added_silence() -> None:
    audio = WavBuilder.join([np.full(8, 0.5, dtype=np.float32)], sampling_rate=8)
    assert audio.duration_ms == 1000
    assert frames(audio.wav_bytes) == [16383] * 8


def test_loud_samples_are_clipped_not_wrapped() -> None:
    audio = WavBuilder.join([np.array([1.5, -2.0], dtype=np.float32)], sampling_rate=4)
    assert frames(audio.wav_bytes) == [32767, -32767]


def test_silence_goes_between_sentences_only() -> None:
    piece = np.ones(4, dtype=np.float32)
    audio = WavBuilder.join([piece, piece], sampling_rate=4)
    # 0.25 s of silence at 4 Hz is one sample
    assert frames(audio.wav_bytes) == [32767] * 4 + [0] + [32767] * 4
    assert audio.duration_ms == 2250


def test_no_sentences_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one sentence"):
        WavBuilder.join([], sampling_rate=24000)
