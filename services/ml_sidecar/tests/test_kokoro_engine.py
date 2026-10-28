"""KokoroEngine over a fake pipeline: the chosen voices, speeds and failure handling."""

from collections.abc import Iterable, Sequence

import numpy as np
import pytest
import torch

from sidecar.kokoro_engine import KokoroEngine, KokoroPipeline, KokoroResult
from sidecar.speech_engine import SpeechFailed, Voice

pytestmark = pytest.mark.unit


class FakeResult:
    def __init__(self, audio: torch.Tensor | None) -> None:
        self._audio = audio

    @property
    def audio(self) -> torch.Tensor | None:
        return self._audio


class FakePipeline:
    def __init__(self, chunks: Sequence[torch.Tensor | None]) -> None:
        self._chunks = list(chunks)
        self.loaded_voices: list[str] = []
        self.calls: list[tuple[str, float, torch.Tensor]] = []

    def __call__(self, text: str, *, voice: torch.Tensor, speed: float) -> Iterable[KokoroResult]:
        self.calls.append((text, speed, voice))
        return [FakeResult(chunk) for chunk in self._chunks]

    def load_voice(self, voice: str) -> torch.Tensor:
        self.loaded_voices.append(voice)
        return torch.full((1,), float(len(self.loaded_voices)))


def engine_with(
    hindi_chunks: Sequence[torch.Tensor | None],
) -> tuple[KokoroEngine, FakePipeline, FakePipeline]:
    hindi = FakePipeline(hindi_chunks)
    english = FakePipeline([torch.zeros(3)])
    pipelines: dict[Voice, KokoroPipeline] = {"hin": hindi, "eng": english}
    return KokoroEngine(pipelines), hindi, english


def test_hindi_uses_the_blended_female_voices_a_little_faster() -> None:
    engine, hindi, english = engine_with([torch.zeros(2)])
    engine.speak("वाह!", "hin")
    assert hindi.loaded_voices == ["hf_alpha,hf_beta"]
    assert english.loaded_voices == ["af_heart"]
    text, speed, _ = hindi.calls[0]
    assert (text, speed) == ("वाह!", 1.1)


def test_english_keeps_normal_speed() -> None:
    engine, _, english = engine_with([torch.zeros(2)])
    engine.speak("Well done!", "eng")
    assert english.calls[0][1] == 1.0


def test_a_long_sentence_spoken_in_chunks_comes_back_as_one_waveform() -> None:
    engine, _, _ = engine_with([torch.full((2,), 0.25), torch.full((3,), -0.5)])
    waveform = engine.speak("एक लंबा वाक्य", "hin")
    assert waveform.dtype == np.float32
    assert waveform.tolist() == [0.25, 0.25, -0.5, -0.5, -0.5]


def test_a_chunk_without_audio_raises_instead_of_dropping_words() -> None:
    engine, _, _ = engine_with([torch.zeros(2), None])
    with pytest.raises(SpeechFailed, match="chunk without audio for a hin sentence"):
        engine.speak("वाह!", "hin")


def test_no_audio_at_all_raises() -> None:
    engine, _, _ = engine_with([])
    with pytest.raises(SpeechFailed, match="no audio for a hin sentence"):
        engine.speak("वाह!", "hin")


def test_reports_its_model_and_sampling_rate() -> None:
    engine, _, _ = engine_with([torch.zeros(1)])
    assert engine.models_loaded() == ["hexgrad/Kokoro-82M"]
    assert engine.sampling_rate == 24000
