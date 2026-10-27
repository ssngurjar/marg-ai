"""AudioAnalyser: silent, short and long notes are caught before transcription (s06 §4.4)."""

import io
import math
import wave
from array import array

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.enums import AudioVerdict
from app.domain.models.voice import AudioStats, VoiceLimits
from app.domain.rules.audio_analyser import AudioAnalyser

pytestmark = pytest.mark.unit

RATE = 16000
LIMITS = VoiceLimits(min_duration_ms=700, min_voiced_ms=400, max_duration_ms=120_000)


def tone(duration_ms: int, amplitude: int = 8000, rate: int = RATE) -> bytes:
    """A 220 Hz tone, as mono 16-bit PCM: stands in for speech loudness."""
    count = rate * duration_ms // 1000
    samples = array(
        "h", (int(amplitude * math.sin(2 * math.pi * 220 * n / rate)) for n in range(count))
    )
    return samples.tobytes()


def silence(duration_ms: int, rate: int = RATE) -> bytes:
    return bytes(2 * (rate * duration_ms // 1000))


def wav(pcm: bytes, *, channels: int = 1, width: int = 2, rate: int = RATE) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(width)
        writer.setframerate(rate)
        writer.writeframes(pcm)
    return buffer.getvalue()


def stats(duration_ms: int, voiced_ms: int) -> AudioStats:
    return AudioStats(duration_ms=duration_ms, voiced_ms=voiced_ms, peak_dbfs=-6.0)


# --- measuring ---------------------------------------------------------------------------------


def test_a_spoken_note_is_mostly_voiced() -> None:
    measured = AudioAnalyser.analyse_wav(wav(silence(500) + tone(2000) + silence(500)))
    assert measured.duration_ms == 3000
    assert measured.voiced_ms == 2000
    assert -13 < measured.peak_dbfs < -12  # 8000 / 32768


def test_a_silent_note_has_no_voiced_time_and_the_silence_floor_as_peak() -> None:
    measured = AudioAnalyser.analyse_wav(wav(silence(3000)))
    assert measured == AudioStats(duration_ms=3000, voiced_ms=0, peak_dbfs=-120.0)


def test_hiss_below_the_speech_threshold_is_not_voiced() -> None:
    measured = AudioAnalyser.analyse_wav(wav(tone(2000, amplitude=100)))  # about -50 dBFS
    assert measured.voiced_ms == 0


def test_an_empty_recording_is_zero_long() -> None:
    assert AudioAnalyser.analyse_wav(wav(b"")) == AudioStats(0, 0, -120.0)


@pytest.mark.parametrize(("channels", "width"), [(2, 2), (1, 1)], ids=["stereo", "8-bit"])
def test_only_mono_16_bit_wav_is_accepted(channels: int, width: int) -> None:
    with pytest.raises(ValueError, match="mono 16-bit PCM"):
        AudioAnalyser.analyse_wav(wav(bytes(4 * RATE), channels=channels, width=width))


@pytest.mark.parametrize("rate", [0, -16000])
def test_a_sample_rate_that_isnt_positive_is_refused(rate: int) -> None:
    with pytest.raises(ValueError, match="positive sample rate"):
        AudioAnalyser.analyse_pcm16(tone(100), rate)


def test_not_wav_at_all_is_refused() -> None:
    with pytest.raises(wave.Error):
        AudioAnalyser.analyse_wav(b"OggS not a wav")


@given(
    pieces=st.lists(st.tuples(st.integers(1, 400), st.integers(0, 20000)), min_size=1, max_size=8),
    trailing_bytes=st.integers(0, 39),
)
def test_voiced_time_is_never_more_than_the_clip(
    pieces: list[tuple[int, int]], trailing_bytes: int
) -> None:
    pcm = b"".join(tone(length, amplitude) for length, amplitude in pieces)
    measured = AudioAnalyser.analyse_pcm16(pcm + b"\x7f" * trailing_bytes, RATE)
    assert 0 <= measured.voiced_ms <= measured.duration_ms


@given(duration_ms=st.integers(20, 2000), amplitude=st.integers(50, 16000))
def test_a_louder_note_is_never_less_voiced(duration_ms: int, amplitude: int) -> None:
    quiet = AudioAnalyser.analyse_pcm16(tone(duration_ms, amplitude), RATE)
    loud = AudioAnalyser.analyse_pcm16(tone(duration_ms, min(amplitude * 2, 32767)), RATE)
    assert loud.voiced_ms >= quiet.voiced_ms


# --- the verdict -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("measured", "expected"),
    [
        (stats(3000, 2000), AudioVerdict.OK),
        (stats(700, 400), AudioVerdict.OK),  # both minimums exactly
        (stats(699, 699), AudioVerdict.TOO_SHORT),
        (stats(0, 0), AudioVerdict.TOO_SHORT),
        (stats(3000, 399), AudioVerdict.SILENT),
        (stats(3000, 0), AudioVerdict.SILENT),
        (stats(120_000, 90_000), AudioVerdict.OK),  # the maximum exactly
        (stats(120_001, 90_000), AudioVerdict.TOO_LONG),
        (stats(600_000, 0), AudioVerdict.TOO_LONG),  # too long wins over silent
    ],
)
def test_the_verdict_at_each_boundary(measured: AudioStats, expected: AudioVerdict) -> None:
    assert AudioAnalyser.verdict(measured, LIMITS) is expected
