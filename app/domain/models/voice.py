"""What a voice note measures, and the limits it's checked against (s06 §4.4)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AudioStats:
    duration_ms: int
    voiced_ms: int  # 20 ms frames whose loudness is above the speech threshold
    peak_dbfs: float


@dataclass(frozen=True, slots=True)
class VoiceLimits:
    min_duration_ms: int  # MIN_VOICE_NOTE_MS
    min_voiced_ms: int  # MIN_VOICED_MS
    max_duration_ms: int  # MAX_VOICE_NOTE_SECONDS, in milliseconds
