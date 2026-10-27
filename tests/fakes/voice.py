"""Fakes for the voice ports (s06): scripted, recording, offline."""

import io
import math
import wave
from array import array
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID, uuid4

from app.audio.audio_transcoder import VOICE_NOTE_MIME
from app.core.errors import MargError
from app.domain.enums import Language
from app.domain.models.base import UserHash
from app.domain.models.message import AudioClip, MediaRef, Transcript
from app.domain.models.usage import StepUsage
from app.domain.models.voice import VoiceLimits
from app.domain.rules.register_detector import RegisterDetector
from app.pipeline.orchestrator import VoiceSteps
from app.providers.ports import TranscriptionHints

RATE = 16000
LIMITS = VoiceLimits(min_duration_ms=700, min_voiced_ms=300, max_duration_ms=180_000)
STT_USAGE = StepUsage(
    provider="meta_model_api",
    model="muse-voice-transcribe-1.0",
    input_tokens=None,
    output_tokens=None,
    audio_seconds=Decimal(3),
    cost_usd=Decimal("0.000150"),
)
TTS_USAGE = StepUsage(
    provider="ml_sidecar",
    model="facebook/mms-tts-hin",
    input_tokens=None,
    output_tokens=None,
    audio_seconds=Decimal("4.5"),
    cost_usd=Decimal("0"),
)
VOICE_NOTE = AudioClip(data=b"OggS fake voice note", mime_type=VOICE_NOTE_MIME, duration_ms=4500)


def wav_of(spoken_ms: int, silence_ms: int = 0, amplitude: int = 8000) -> AudioClip:
    """A 16 kHz mono WAV: a tone standing in for speech, then silence."""
    samples = array("h")
    for n in range(RATE * spoken_ms // 1000):
        samples.append(int(amplitude * math.sin(2 * math.pi * 220 * n / RATE)))
    samples.extend([0] * (RATE * silence_ms // 1000))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(RATE)
        writer.writeframes(samples.tobytes())
    return AudioClip(
        data=buffer.getvalue(), mime_type="audio/wav", duration_ms=spoken_ms + silence_ms
    )


SPOKEN_WAV = wav_of(3000)


class FakeMediaFetcher:
    """Satisfies `MediaFetcher`."""

    def __init__(self, error: MargError | None = None) -> None:
        self.refs: list[MediaRef] = []
        self._error = error

    async def fetch(self, ref: MediaRef) -> AudioClip:
        self.refs.append(ref)
        if self._error is not None:
            raise self._error
        return AudioClip(data=b"OggS user voice note", mime_type=ref.mime_type, duration_ms=None)


class FakeAudioConverter:
    """Satisfies `AudioConverter`: hands back the scripted WAV for every note."""

    def __init__(self, wav: AudioClip = SPOKEN_WAV, error: MargError | None = None) -> None:
        self.converted = 0
        self._wav = wav
        self._error = error

    async def to_stt_wav(self, clip: AudioClip) -> AudioClip:
        self.converted += 1
        if self._error is not None:
            raise self._error
        return self._wav


class FakeTranscriber:
    """Satisfies `Transcriber`: scripted transcripts or errors, in order."""

    def __init__(self, outputs: Sequence[str | MargError] = ()) -> None:
        self.hints: list[TranscriptionHints] = []
        self._outputs = list(outputs)

    async def transcribe(
        self, clip: AudioClip, hints: TranscriptionHints
    ) -> tuple[Transcript, StepUsage]:
        self.hints.append(hints)
        output = self._outputs.pop(0)
        if isinstance(output, MargError):
            raise output
        transcript = Transcript(
            text=output.strip(),
            language=RegisterDetector.detect(output),
            confidence=None,
            audio_duration_ms=clip.duration_ms or 0,
        )
        return transcript, STT_USAGE


@dataclass
class SpokenRequest:
    text: str
    language: Language


class FakeSynthesizer:
    """Satisfies `Synthesizer`."""

    def __init__(self, error: MargError | None = None) -> None:
        self.requests: list[SpokenRequest] = []
        self._error = error

    async def synthesize(self, text: str, language: Language) -> tuple[AudioClip, StepUsage]:
        self.requests.append(SpokenRequest(text, language))
        if self._error is not None:
            raise self._error
        return VOICE_NOTE, TTS_USAGE


@dataclass
class MemoryReplyAudioStore:
    """Satisfies `ReplyAudioStore`."""

    error: MargError | None = None
    saved: dict[UUID, AudioClip] = field(default_factory=dict)
    owners: dict[UUID, UserHash] = field(default_factory=dict)

    async def save(self, user_hash: UserHash, clip: AudioClip) -> UUID:
        if self.error is not None:
            raise self.error
        blob_id = uuid4()
        self.saved[blob_id] = clip
        self.owners[blob_id] = user_hash
        return blob_id

    async def load_audio(self, blob_id: UUID) -> AudioClip | None:
        return self.saved.get(blob_id)


@dataclass
class FakeVoice:
    """Every voice fake, so a test can script one and inspect the others."""

    fetcher: FakeMediaFetcher = field(default_factory=FakeMediaFetcher)
    converter: FakeAudioConverter = field(default_factory=FakeAudioConverter)
    transcriber: FakeTranscriber = field(default_factory=FakeTranscriber)
    synthesizer: FakeSynthesizer = field(default_factory=FakeSynthesizer)
    store: MemoryReplyAudioStore = field(default_factory=MemoryReplyAudioStore)
    reply_audio_for_text_input: bool = False

    def steps(self) -> VoiceSteps:
        return VoiceSteps(
            fetcher=self.fetcher,
            converter=self.converter,
            transcriber=self.transcriber,
            synthesizer=self.synthesizer,
            audio_store=self.store,
            limits=LIMITS,
            reply_audio_for_text_input=self.reply_audio_for_text_input,
        )
