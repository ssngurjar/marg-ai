"""MmsEngine: Meta's MMS-TTS (VITS, about 36M parameters) speaking Hindi and English on a CPU.

`facebook/mms-tts-hin` reads Devanagari directly, and `facebook/mms-tts-eng` English. The
weights are CC-BY-NC 4.0, so voice replies stay off (VOICE_REPLIES_ENABLED=false) until the
organisers rule on that licence (s06 decisions log, 2026-10-29).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Protocol

import numpy as np
import torch

from sidecar.speech_engine import Engine, SpeechFailed, Voice, Waveform


class MmsTokenizer(Protocol):
    def __call__(self, text: str, *, return_tensors: str) -> Mapping[str, torch.Tensor]: ...


class MmsOutput(Protocol):
    @property
    def waveform(self) -> torch.Tensor: ...


class MmsModel(Protocol):
    """The part of `transformers.VitsModel` Marg uses (transformers ships no type information)."""

    def __call__(self, *, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> MmsOutput: ...


@dataclass(frozen=True, slots=True)
class MmsVoice:
    tokenizer: MmsTokenizer
    model: MmsModel


class MmsEngine:
    name: Engine = "mms"
    MODELS: ClassVar[dict[Voice, str]] = {
        "hin": "facebook/mms-tts-hin",
        "eng": "facebook/mms-tts-eng",
    }

    def __init__(
        self, voices: Mapping[Voice, MmsVoice], *, sampling_rate: int, device: str
    ) -> None:
        self._voices = dict(voices)
        self._device = device
        self.sampling_rate: int = sampling_rate

    @classmethod
    def load(cls, device: str) -> "MmsEngine":
        # transformers ships no type information; MmsTokenizer and MmsModel above type what is used.
        from transformers import (  # type: ignore[import-untyped]  # noqa: PLC0415  # heavy; loaded at startup only
            AutoTokenizer,
            VitsModel,
        )

        voices: dict[Voice, MmsVoice] = {}
        rates: set[int] = set()
        for voice, name in cls.MODELS.items():
            model = VitsModel.from_pretrained(name).to(device).eval()
            rates.add(int(model.config.sampling_rate))
            voices[voice] = MmsVoice(tokenizer=AutoTokenizer.from_pretrained(name), model=model)
        if len(rates) != 1:
            raise SpeechFailed(f"the MMS voices disagree on sampling rate: {sorted(rates)}")
        return cls(voices, sampling_rate=rates.pop(), device=device)

    def models_loaded(self) -> list[str]:
        return list(self.MODELS.values())

    def speak(self, sentence: str, voice: Voice) -> Waveform:
        mms_voice = self._voices[voice]
        tokens = mms_voice.tokenizer(sentence, return_tensors="pt")
        input_ids = tokens["input_ids"].to(self._device)
        if input_ids.numel() == 0:
            raise SpeechFailed(f"MMS has no letters to read in this {voice} sentence")
        attention_mask = tokens["attention_mask"].to(self._device)
        with torch.inference_mode():
            output = mms_voice.model(input_ids=input_ids, attention_mask=attention_mask)
        waveform = output.waveform.squeeze().float().cpu().numpy().astype(np.float32)
        if waveform.size == 0:
            raise SpeechFailed(f"MMS returned no audio for a {voice} sentence")
        return waveform
