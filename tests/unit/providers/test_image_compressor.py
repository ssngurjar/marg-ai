"""ImageCompressor: a khoj card PNG becomes a small JPEG (s10b §4.13). Runs the real ffmpeg."""

import stat
from pathlib import Path

import pytest

from app.audio.ffmpeg_runner import FfmpegRunner
from app.core.errors import TranscodeFailed
from app.domain.models.message import ImageClip
from app.providers.image.image_compressor import ImageCompressor
from tests.fakes.image import TINY_PNG

pytestmark = pytest.mark.unit


async def big_png() -> bytes:
    """A 1024x1024 PNG of noise, like Muse Image's size, made by ffmpeg itself."""
    runner = FfmpegRunner(timeout_s=20)
    return await runner.run(
        ("-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
         "cellauto=s=1024x1024", "-frames:v", "1", "-c:v", "png", "-f", "image2pipe", "pipe:1"),
        b"",
    )  # fmt: skip


async def test_a_card_sized_png_becomes_an_800_pixel_jpeg_far_under_the_cap() -> None:
    png = await big_png()
    jpeg = await ImageCompressor(FfmpegRunner(timeout_s=20)).to_jpeg(
        ImageClip(data=png, mime_type="image/png")
    )
    assert jpeg.mime_type == "image/jpeg"
    assert jpeg.data.startswith(b"\xff\xd8\xff")
    assert len(jpeg.data) < 2_097_152  # media_blobs' cap
    assert jpeg_width(jpeg.data) == 800


def jpeg_width(data: bytes) -> int:
    """The width in a baseline JPEG's start-of-frame marker: FF C0, length (2), precision (1),
    height (2), width (2)."""
    frame = data.find(b"\xff\xc0")
    return int.from_bytes(data[frame + 7 : frame + 9])


async def test_a_small_image_is_not_blown_up() -> None:
    jpeg = await ImageCompressor(FfmpegRunner(timeout_s=10)).to_jpeg(
        ImageClip(data=TINY_PNG, mime_type="image/png")
    )
    assert jpeg.data.startswith(b"\xff\xd8\xff")


async def test_not_an_image_fails_with_ffmpegs_reason() -> None:
    with pytest.raises(TranscodeFailed, match=r"ffmpeg exited \d+"):
        await ImageCompressor(FfmpegRunner(timeout_s=10)).to_jpeg(
            ImageClip(data=b"not an image", mime_type="image/png")
        )


async def test_output_that_isnt_a_jpeg_is_refused(tmp_path: Path) -> None:
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\ncat > /dev/null; printf 'GIF89a'\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(TranscodeFailed, match="didn't produce a JPEG"):
        await ImageCompressor(FfmpegRunner(timeout_s=5, ffmpeg=str(fake))).to_jpeg(
            ImageClip(data=TINY_PNG, mime_type="image/png")
        )
