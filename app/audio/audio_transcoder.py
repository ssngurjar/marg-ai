"""AudioTranscoder: ffmpeg conversions for speech-to-text and voice notes (s06 §4.3).

ffmpeg runs through FfmpegRunner (an argument list, stdin to stdout, a time limit). For
speech-to-text it writes raw PCM and the WAV header is written here: ffmpeg can't seek back on a
pipe, so its own header would carry no length. A voice note can be raised or lowered in pitch
at the same speed (TTS_PITCH, default 1.0: as spoken). That is signal processing, not another
model; a raised male voice still sounds male (owner, 2026-10-29).
"""

import io
import wave
from collections.abc import Sequence
from typing import ClassVar, Final

from app.audio.ffmpeg_runner import FfmpegRunner
from app.core.errors import ConfigError, TranscodeFailed
from app.domain.models.message import AudioClip

VOICE_NOTE_MIME: Final = "audio/ogg; codecs=opus"
STT_SAMPLE_RATE: Final = 16000
STT_SAMPLE_BYTES: Final = 2  # 16-bit


class AudioTranscoder:
    STT_WAV_ARGS: ClassVar[tuple[str, ...]] = (
        "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-vn", "-ac", "1",
        "-ar", str(STT_SAMPLE_RATE), "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1",
    )  # fmt: skip
    VOICE_NOTE_INPUT: ClassVar[tuple[str, ...]] = (
        "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-vn", "-ac", "1",
    )  # fmt: skip
    VOICE_NOTE_OUTPUT: ClassVar[tuple[str, ...]] = (
        "-ar", "48000", "-c:a", "libopus", "-b:a", "24k", "-application", "voip", "-f", "ogg",
        "pipe:1",
    )  # fmt: skip
    MIN_PITCH: ClassVar[float] = 0.5  # ffmpeg's atempo takes 0.5 to 2 in one step
    MAX_PITCH: ClassVar[float] = 2.0

    def __init__(
        self, timeout_s: float, ffmpeg: str = "ffmpeg", *, voice_pitch: float = 1.0
    ) -> None:
        """Raises ConfigError for a pitch outside 0.5-2."""
        if not self.MIN_PITCH <= voice_pitch <= self.MAX_PITCH:
            raise ConfigError(f"TTS_PITCH must be between 0.5 and 2, got {voice_pitch}")
        self._runner = FfmpegRunner(timeout_s, ffmpeg)
        self._voice_pitch = voice_pitch

    async def to_stt_wav(self, clip: AudioClip) -> AudioClip:
        """Any voice note → mono 16-bit PCM WAV at 16 kHz, what Muse Voice Transcribe takes."""
        pcm = await self._run(self.STT_WAV_ARGS, clip.data)
        if len(pcm) % STT_SAMPLE_BYTES:
            raise TranscodeFailed(f"ffmpeg returned {len(pcm)} bytes, not whole 16-bit samples")
        wav_bytes = io.BytesIO()
        with wave.open(wav_bytes, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(STT_SAMPLE_BYTES)
            wav.setframerate(STT_SAMPLE_RATE)
            wav.writeframes(pcm)
        samples = len(pcm) // STT_SAMPLE_BYTES
        return AudioClip(
            data=wav_bytes.getvalue(),
            mime_type="audio/wav",
            duration_ms=samples * 1000 // STT_SAMPLE_RATE,
        )

    async def to_voice_note(self, clip: AudioClip) -> AudioClip:
        """Synthesised WAV → a WhatsApp voice note (OGG/Opus, mono), at TTS_PITCH. Raises
        TranscodeFailed when a pitch change is asked for and the clip isn't a readable WAV."""
        pitch_filter: tuple[str, ...] = ()
        if self._voice_pitch != 1.0:
            pitch_filter = ("-af", self._pitch_filter(self._wav_rate(clip.data)))
        args = (*self.VOICE_NOTE_INPUT, *pitch_filter, *self.VOICE_NOTE_OUTPUT)
        data = await self._run(args, clip.data)
        return AudioClip(data=data, mime_type=VOICE_NOTE_MIME, duration_ms=clip.duration_ms)

    def _pitch_filter(self, rate: int) -> str:
        """Play faster to raise the pitch, then slow back to the same speed."""
        raised = round(rate * self._voice_pitch)
        return f"asetrate={raised},aresample={rate},atempo={1 / self._voice_pitch:.6f}"

    @staticmethod
    def _wav_rate(data: bytes) -> int:
        try:
            with wave.open(io.BytesIO(data), "rb") as wav:
                return wav.getframerate()
        except (wave.Error, EOFError) as exc:
            raise TranscodeFailed(f"speech to pitch isn't a readable WAV: {exc}") from exc

    async def check_encoders(self) -> None:
        """Startup readiness: ffmpeg must have libopus and pcm_s16le. Raises ConfigError."""
        output = await self._run(("-hide_banner", "-encoders"), b"")
        listed = output.decode("utf-8", errors="replace")
        missing = [name for name in ("libopus", "pcm_s16le") if name not in listed]
        if missing:
            raise ConfigError(f"ffmpeg lacks {', '.join(missing)}")

    async def _run(self, args: Sequence[str], data: bytes) -> bytes:
        return await self._runner.run(args, data)
