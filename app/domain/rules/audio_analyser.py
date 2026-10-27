"""AudioAnalyser: is a voice note worth transcribing? (s06 §4.4). Pure, standard library only.

Checked before the speech-to-text call, so a silent or accidental note costs nothing and is
answered faster. Long notes are refused, never cut (CLAUDE.md §4).
"""

import io
import math
import wave
from array import array
from typing import ClassVar

from app.domain.enums import AudioVerdict
from app.domain.models.voice import AudioStats, VoiceLimits


class AudioAnalyser:
    FRAME_MS: ClassVar[int] = 20
    MONO_PCM16: ClassVar[tuple[int, int]] = (1, 2)  # one channel, two bytes per sample
    SPEECH_THRESHOLD_DBFS: ClassVar[float] = -45.0  # calibrate on the S0 samples (spike A)
    FULL_SCALE: ClassVar[float] = 32768.0
    SILENCE_DBFS: ClassVar[float] = -120.0  # what an all-zero frame counts as

    @staticmethod
    def analyse_wav(wav_bytes: bytes) -> AudioStats:
        """Stats for a mono 16-bit PCM WAV (what AudioTranscoder.to_stt_wav produces)."""
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth()) != AudioAnalyser.MONO_PCM16:
                raise ValueError("analyse_wav needs mono 16-bit PCM")
            rate = wav.getframerate()
            pcm = wav.readframes(wav.getnframes())
        return AudioAnalyser.analyse_pcm16(pcm, rate)

    @staticmethod
    def analyse_pcm16(pcm: bytes, sample_rate: int) -> AudioStats:
        if sample_rate <= 0:
            raise ValueError(f"analyse_pcm16 needs a positive sample rate, got {sample_rate}")
        samples = array("h")
        samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
        duration_ms = len(samples) * 1000 // sample_rate
        frame = max(sample_rate * AudioAnalyser.FRAME_MS // 1000, 1)
        voiced_frames = 0
        peak = 0
        for start in range(0, len(samples), frame):
            window = samples[start : start + frame]
            if not window:
                continue
            loudest = max(abs(sample) for sample in window)
            peak = max(peak, loudest)
            if (
                AudioAnalyser._dbfs(AudioAnalyser._rms(window))
                > AudioAnalyser.SPEECH_THRESHOLD_DBFS
            ):
                voiced_frames += 1
        return AudioStats(
            duration_ms=duration_ms,
            # a voiced partial frame at the end counts whole; never more than the clip itself
            voiced_ms=min(voiced_frames * AudioAnalyser.FRAME_MS, duration_ms),
            peak_dbfs=AudioAnalyser._dbfs(float(peak)),
        )

    @staticmethod
    def verdict(stats: AudioStats, limits: VoiceLimits) -> AudioVerdict:
        if stats.duration_ms > limits.max_duration_ms:
            return AudioVerdict.TOO_LONG
        if stats.duration_ms < limits.min_duration_ms:
            return AudioVerdict.TOO_SHORT
        if stats.voiced_ms < limits.min_voiced_ms:
            return AudioVerdict.SILENT
        return AudioVerdict.OK

    @staticmethod
    def _rms(window: array[int]) -> float:
        return math.sqrt(sum(sample * sample for sample in window) / len(window))

    @staticmethod
    def _dbfs(level: float) -> float:
        if level <= 0:
            return AudioAnalyser.SILENCE_DBFS
        return 20 * math.log10(level / AudioAnalyser.FULL_SCALE)
