"""AudioTranscoder: ffmpeg in a time limit, never a shell (s06 §4.3, CLAUDE.md §12).

The conversions run the real ffmpeg (CI installs it, the image ships it). The failure paths use
small fake executables so they're quick and certain.
"""

import io
import math
import stat
import wave
from array import array
from pathlib import Path

import pytest

from app.audio.audio_transcoder import STT_SAMPLE_RATE, VOICE_NOTE_MIME, AudioTranscoder
from app.core.errors import ConfigError, TranscodeFailed, TranscodeTimeout
from app.domain.models.message import AudioClip
from app.domain.rules.audio_analyser import AudioAnalyser

pytestmark = pytest.mark.unit


def stereo_wav(duration_ms: int, rate: int = 44100) -> bytes:
    """A loud 220 Hz tone in CD-quality stereo, unlike anything the STT takes directly."""
    count = rate * duration_ms // 1000
    left_right = array("h")
    for n in range(count):
        sample = int(8000 * math.sin(2 * math.pi * 220 * n / rate))
        left_right.extend((sample, sample))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(left_right.tobytes())
    return buffer.getvalue()


def fake_ffmpeg(tmp_path: Path, script: str) -> str:
    path = tmp_path / "ffmpeg"
    path.write_text(f"#!/bin/sh\n{script}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


CLIP = AudioClip(data=stereo_wav(1500), mime_type="audio/wav", duration_ms=None)


async def test_a_voice_note_becomes_mono_16k_wav_for_speech_to_text() -> None:
    converted = await AudioTranscoder(timeout_s=10).to_stt_wav(CLIP)
    assert converted.mime_type == "audio/wav"
    assert converted.duration_ms == 1500
    with wave.open(io.BytesIO(converted.data), "rb") as result:
        assert (result.getnchannels(), result.getsampwidth()) == (1, 2)
        assert result.getframerate() == STT_SAMPLE_RATE
    assert AudioAnalyser.analyse_wav(converted.data).voiced_ms >= 1400


async def test_synthesised_speech_becomes_an_ogg_opus_voice_note() -> None:
    clip = AudioClip(data=stereo_wav(1000), mime_type="audio/wav", duration_ms=1000)
    note = await AudioTranscoder(timeout_s=10).to_voice_note(clip)
    assert note.mime_type == VOICE_NOTE_MIME
    assert note.data.startswith(b"OggS")
    assert b"OpusHead" in note.data[:200]
    assert note.duration_ms == 1000


async def test_the_installed_ffmpeg_has_the_encoders_we_need() -> None:
    await AudioTranscoder(timeout_s=10).check_encoders()


@pytest.mark.parametrize("data", [b"", b"not audio at all", b"OggS\x00broken"])
async def test_input_ffmpeg_cant_read_fails_with_its_reason(data: bytes) -> None:
    clip = AudioClip(data=data, mime_type="audio/ogg", duration_ms=None)
    with pytest.raises(TranscodeFailed, match=r"ffmpeg exited \d+: .+"):
        await AudioTranscoder(timeout_s=10).to_stt_wav(clip)


async def test_a_missing_ffmpeg_fails_as_could_not_start(tmp_path: Path) -> None:
    transcoder = AudioTranscoder(timeout_s=1, ffmpeg=str(tmp_path / "no-ffmpeg-here"))
    with pytest.raises(TranscodeFailed, match="ffmpeg could not start: FileNotFoundError"):
        await transcoder.to_stt_wav(CLIP)


async def test_an_ffmpeg_that_hangs_is_killed_at_the_time_limit(tmp_path: Path) -> None:
    transcoder = AudioTranscoder(timeout_s=0.3, ffmpeg=fake_ffmpeg(tmp_path, "exec sleep 30"))
    with pytest.raises(TranscodeTimeout, match="ffmpeg timed out"):
        await transcoder.to_stt_wav(CLIP)


async def test_only_the_tail_of_ffmpeg_errors_is_kept(tmp_path: Path) -> None:
    noisy = fake_ffmpeg(tmp_path, "head -c 5000 /dev/zero | tr '\\0' x >&2; printf END >&2; exit 1")
    with pytest.raises(TranscodeFailed) as raised:
        await AudioTranscoder(timeout_s=5, ffmpeg=noisy).to_stt_wav(CLIP)
    message = str(raised.value)
    assert message.endswith("END")
    assert len(message) < 400


async def test_a_half_sample_from_ffmpeg_is_refused_not_passed_on(tmp_path: Path) -> None:
    odd = fake_ffmpeg(tmp_path, "cat > /dev/null; printf abc")
    with pytest.raises(TranscodeFailed, match="returned 3 bytes, not whole 16-bit samples"):
        await AudioTranscoder(timeout_s=5, ffmpeg=odd).to_stt_wav(CLIP)


async def test_the_wav_header_states_the_true_length() -> None:
    """Regression: ffmpeg's own WAV header on a pipe said 0xFFFFFFFF (a 37-hour clip)."""
    converted = await AudioTranscoder(timeout_s=10).to_stt_wav(CLIP)
    with wave.open(io.BytesIO(converted.data), "rb") as result:
        assert result.getnframes() == STT_SAMPLE_RATE * 1500 // 1000
    assert converted.data[4:8] != b"\xff\xff\xff\xff"


async def test_an_ffmpeg_without_libopus_fails_the_startup_check(tmp_path: Path) -> None:
    listing = fake_ffmpeg(tmp_path, "echo ' A....D pcm_s16le   PCM signed 16-bit'")
    with pytest.raises(ConfigError, match="ffmpeg lacks libopus"):
        await AudioTranscoder(timeout_s=5, ffmpeg=listing).check_encoders()
