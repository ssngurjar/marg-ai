"""WhatsAppMediaFetcher: a user's voice note or photo, downloaded for this turn only (s06 §4.2,
s10b §4.14).

1. GET /{media_id} → url, mime type, sha256, size. Too big → MediaTooLarge, before downloading.
   Voice notes and photos have their own size caps; a photo must be a JPEG, PNG or WebP.
2. GET url with the same token (it expires after 5 minutes; a 404 re-asks for a fresh url once).
3. Streamed, and stopped past the size cap, so a wrong declared size can't exhaust memory.
4. The SHA-256 must match. Neither the audio nor the photo is ever stored (data-model §4).

The whole flow runs under the shared retry policy: a 5xx, a timeout or a checksum mismatch is
tried again (a mismatch once), a 4xx or a file over the cap is not.
"""

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import ClassVar, Final

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from app.channels.whatsapp.graph_error_classifier import GraphErrorClassifier
from app.constants.whatsapp import PROVIDER
from app.core.clock import Clock
from app.core.errors import (
    MediaTooLarge,
    MediaUnsupported,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.domain.models.message import AudioClip, ImageClip, MediaRef
from app.providers.http import RetryPolicy

PHOTO_TYPES: Final = frozenset({"image/jpeg", "image/png", "image/webp"})


class _MediaInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    url: str
    mime_type: str
    sha256: str
    file_size: int


@dataclass(frozen=True, slots=True)
class MediaFetchConfig:
    graph_base_url: str
    access_token: SecretStr
    timeout_s: float
    max_bytes: int  # MAX_INBOUND_AUDIO_BYTES
    max_image_bytes: int  # MAX_INBOUND_IMAGE_BYTES


class WhatsAppMediaFetcher:
    """Satisfies `MediaFetcher` for WhatsApp media ids."""

    NOT_FOUND: ClassVar[int] = 404

    def __init__(
        self,
        *,
        config: MediaFetchConfig,
        retry: RetryPolicy,
        clock: Clock,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._http = http if http is not None else httpx.AsyncClient()
        self._config = config
        self._retry = retry
        self._clock = clock

    async def aclose(self) -> None:
        await self._http.aclose()

    async def fetch(self, ref: MediaRef) -> AudioClip:
        download = await self._fetch(ref, self._config.max_bytes, "voice note")
        return AudioClip(data=download.data, mime_type=download.mime_type, duration_ms=None)

    async def fetch_image(self, ref: MediaRef) -> ImageClip:
        """Raises MediaUnsupported for anything but a JPEG, PNG or WebP."""
        download = await self._fetch(ref, self._config.max_image_bytes, "photo")
        mime_type = download.mime_type.split(";")[0].strip().lower()
        if mime_type not in PHOTO_TYPES:
            raise MediaUnsupported(f"photo type {mime_type} is not accepted")
        return ImageClip(data=download.data, mime_type=mime_type)

    async def _fetch(self, ref: MediaRef, max_bytes: int, what: str) -> "_Download":
        media_id = ref.provider_media_id
        if media_id is None:
            raise ValueError("WhatsAppMediaFetcher needs a WhatsApp media id")
        deadline = self._clock.now() + timedelta(seconds=self._config.timeout_s)
        return await self._retry.run(
            lambda: self._fetch_once(media_id, max_bytes, what), deadline=deadline
        )

    async def _fetch_once(self, media_id: str, max_bytes: int, what: str) -> "_Download":
        info = await self._info(media_id)
        if info.file_size > max_bytes:
            raise MediaTooLarge(f"{what} is {info.file_size} bytes")
        try:
            data = await self._download(info.url, max_bytes, what)
        except _UrlExpired:
            info = await self._info(media_id)
            try:
                data = await self._download(info.url, max_bytes, what)
            except _UrlExpired as exc:
                raise ProviderUnavailable("media url expired twice", provider=PROVIDER) from exc
        if hashlib.sha256(data).hexdigest() != info.sha256.lower():
            raise ProviderResponseInvalid(f"{what} checksum mismatch", provider=PROVIDER)
        return _Download(data=data, mime_type=info.mime_type)

    async def _info(self, media_id: str) -> _MediaInfo:
        response = await self._get(f"{self._config.graph_base_url.rstrip('/')}/{media_id}")
        try:
            return _MediaInfo.model_validate_json(response.content)
        except ValidationError as exc:
            raise ProviderResponseInvalid(
                "graph api media info unexpected", provider=PROVIDER
            ) from exc

    async def _download(self, url: str, max_bytes: int, what: str) -> bytes:
        headers = self._headers()
        try:
            async with self._http.stream(
                "GET", url, headers=headers, timeout=self._config.timeout_s
            ) as response:
                if response.status_code == self.NOT_FOUND:
                    raise _UrlExpired
                if not response.is_success:
                    raise GraphErrorClassifier.classify(
                        response.status_code, await response.aread()
                    )
                received = bytearray()
                async for chunk in response.aiter_bytes():
                    received.extend(chunk)
                    if len(received) > max_bytes:
                        raise MediaTooLarge(f"{what} exceeded the size cap while downloading")
                return bytes(received)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("media download timed out", provider=PROVIDER) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(
                f"media download failed: {type(exc).__name__}", provider=PROVIDER
            ) from exc

    async def _get(self, url: str) -> httpx.Response:
        try:
            response = await self._http.get(
                url, headers=self._headers(), timeout=self._config.timeout_s
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("graph api media info timed out", provider=PROVIDER) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(
                f"graph api media info failed: {type(exc).__name__}", provider=PROVIDER
            ) from exc
        if not response.is_success:
            raise GraphErrorClassifier.classify(response.status_code, response.content)
        return response

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._config.access_token.get_secret_value()}"}


@dataclass(frozen=True, slots=True)
class _Download:
    data: bytes
    mime_type: str


class _UrlExpired(Exception):
    """The media url's 5 minutes ran out: ask for a fresh one (once)."""
