"""ImageCompressor: a khoj card small enough to keep and send (s10b §4.13).

Muse Image returns a 1024x1024 PNG of about 5 MB: over the 2 MB media_blobs cap. ffmpeg (already
in the image for voice) turns it into an 800-pixel JPEG of about 250 KB, with no new dependency.
"""

from typing import ClassVar, Final

from app.audio.ffmpeg_runner import FfmpegRunner
from app.core.errors import TranscodeFailed
from app.domain.models.message import ImageClip

JPEG_SIGNATURE: Final = b"\xff\xd8\xff"


class ImageCompressor:
    CARD_WIDTH: ClassVar[int] = 800
    JPEG_ARGS: ClassVar[tuple[str, ...]] = (
        "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
        "-vf", "scale='min(800,iw)':-2", "-q:v", "5", "-frames:v", "1",
        "-c:v", "mjpeg", "-f", "image2pipe", "pipe:1",
    )  # fmt: skip

    def __init__(self, runner: FfmpegRunner) -> None:
        self._runner = runner

    async def to_jpeg(self, image: ImageClip) -> ImageClip:
        """Raises TranscodeFailed (or TranscodeTimeout)."""
        data = await self._runner.run(self.JPEG_ARGS, image.data)
        if not data.startswith(JPEG_SIGNATURE):
            raise TranscodeFailed("ffmpeg didn't produce a JPEG")
        return ImageClip(data=data, mime_type="image/jpeg")
