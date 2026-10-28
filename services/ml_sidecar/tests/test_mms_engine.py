"""MmsEngine over a fake tokenizer and model: the voice per language, and failures raised."""

from collections.abc import Mapping

import numpy as np
import pytest
import torch

from sidecar.mms_engine import MmsEngine, MmsOutput, MmsVoice
from sidecar.speech_engine import SpeechFailed, Voice

pytestmark = pytest.mark.unit


class FakeTokenizer:
    def __init__(self, token_count: int) -> None:
        self._token_count = token_count
        self.read: list[str] = []

    def __call__(self, text: str, *, return_tensors: str) -> Mapping[str, torch.Tensor]:
        assert return_tensors == "pt"
        self.read.append(text)
        return {
            "input_ids": torch.ones((1, self._token_count), dtype=torch.long),
            "attention_mask": torch.ones((1, self._token_count), dtype=torch.long),
        }


class FakeOutput:
    def __init__(self, waveform: torch.Tensor) -> None:
        self._waveform = waveform

    @property
    def waveform(self) -> torch.Tensor:
        return self._waveform


class FakeModel:
    def __init__(self, samples: int, level: float) -> None:
        self._samples = samples
        self._level = level

    def __call__(self, *, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> MmsOutput:
        assert input_ids.shape == attention_mask.shape
        return FakeOutput(torch.full((1, self._samples), self._level))


def engine_with(
    *, hindi_tokens: int = 3, hindi_samples: int = 4
) -> tuple[MmsEngine, FakeTokenizer, FakeTokenizer]:
    hindi = FakeTokenizer(hindi_tokens)
    english = FakeTokenizer(3)
    voices: dict[Voice, MmsVoice] = {
        "hin": MmsVoice(tokenizer=hindi, model=FakeModel(hindi_samples, 0.25)),
        "eng": MmsVoice(tokenizer=english, model=FakeModel(2, -0.5)),
    }
    return MmsEngine(voices, sampling_rate=16000, device="cpu"), hindi, english


def test_each_language_is_read_by_its_own_voice() -> None:
    engine, hindi, english = engine_with()
    hindi_audio = engine.speak("परछाई घूमती है।", "hin")
    english_audio = engine.speak("Well done!", "eng")
    assert hindi.read == ["परछाई घूमती है।"]
    assert english.read == ["Well done!"]
    assert hindi_audio.tolist() == [0.25] * 4
    assert english_audio.tolist() == [-0.5, -0.5]
    assert hindi_audio.dtype == np.float32


def test_a_sentence_with_no_readable_letters_raises() -> None:
    engine, _, _ = engine_with(hindi_tokens=0)
    with pytest.raises(SpeechFailed, match="no letters to read in this hin sentence"):
        engine.speak("🙂", "hin")


def test_no_audio_back_raises() -> None:
    engine, _, _ = engine_with(hindi_samples=0)
    with pytest.raises(SpeechFailed, match="no audio for a hin sentence"):
        engine.speak("वाह!", "hin")


def test_reports_both_meta_models_and_the_sampling_rate() -> None:
    engine, _, _ = engine_with()
    assert engine.models_loaded() == ["facebook/mms-tts-hin", "facebook/mms-tts-eng"]
    assert engine.sampling_rate == 16000
