"""FfmpegRunner: one ffmpeg run, as an argument list (never a shell), stdin to stdout, inside a
time limit (CLAUDE.md §12). Shared by the voice conversions and the khoj card's JPEG.

On failure the error carries ffmpeg's last 300 bytes of stderr, which describe the codec,
never the media's content.
"""

import asyncio
from collections.abc import Sequence
from typing import ClassVar

from app.core.errors import TranscodeFailed, TranscodeTimeout


class FfmpegRunner:
    STDERR_TAIL: ClassVar[int] = 300

    def __init__(self, timeout_s: float, ffmpeg: str = "ffmpeg") -> None:
        self._timeout_s = timeout_s
        self._ffmpeg = ffmpeg

    async def run(self, args: Sequence[str], data: bytes) -> bytes:
        try:
            process = await asyncio.create_subprocess_exec(
                self._ffmpeg,
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise TranscodeFailed(f"ffmpeg could not start: {type(exc).__name__}") from exc
        try:
            async with asyncio.timeout(self._timeout_s):
                stdout, stderr = await process.communicate(input=data)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise TranscodeTimeout("ffmpeg timed out") from exc
        if process.returncode != 0:
            tail = stderr[-self.STDERR_TAIL :].decode("utf-8", errors="replace").strip()
            raise TranscodeFailed(f"ffmpeg exited {process.returncode}: {tail}")
        return stdout
