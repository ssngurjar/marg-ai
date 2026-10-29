"""The web demo (s14): a page, a session, messages in, and a live trace of each turn.

Thin, like the webhook: the WebDemoIngestor does the checks and the inbox insert; the worker
runs the same pipeline as for WhatsApp. Messages are JSON (a voice note or photo as base64), so
there's no form-parsing dependency. The page follows its turns on `GET /demo/events` (SSE) and
falls back to polling `GET /demo/messages/{id}` when the stream is down; a reloaded page reads the
conversation so far, a page at a time, from `GET /demo/history`. Every response under
/demo carries the security headers of s14 §4.10.
"""

import base64
import binascii
from pathlib import Path
from typing import Annotated, Final
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.demo_view_serializer import DemoViewSerializer
from app.api.deps import (
    get_media_repository,
    get_turn_event_stream,
    get_turn_progress_hub,
    get_user_repository,
    get_web_demo,
)
from app.api.turn_event_stream import TurnEventStream
from app.api.turn_progress_hub import TurnProgressHub
from app.api.web_demo_ingestor import SESSION_TTL, WebDemoIngestor
from app.channels.web.web_message_parser import WebUpload
from app.core.errors import DemoRefused, WebInputInvalid
from app.core.logging import get_logger
from app.domain.enums import MediaPurpose
from app.store.repositories.media_blob_repository import MediaBlobRepository
from app.store.repositories.user_repository import UserRepository

router = APIRouter(prefix="/demo")
logger = get_logger(__name__)

PAGE: Final = Path(__file__).resolve().parents[2] / "static" / "demo" / "index.html"
COOKIE: Final = "marg_session"
HISTORY_PAGE: Final = 20  # turns per page of a reloaded conversation
HISTORY_MAX_PAGE: Final = 50
MAX_BODY_BYTES: Final = 1_500_000  # a 1 MB voice note or photo as base64, plus a little
SECURITY_HEADERS: Final = {
    "Content-Security-Policy": (
        "default-src 'self'; media-src 'self' blob:; connect-src 'self'; "
        "img-src 'self' data: blob:; "
        "style-src 'self'; script-src 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}
LOOPBACK: Final = frozenset({"127.0.0.1", "::1"})

DemoDep = Annotated[WebDemoIngestor, Depends(get_web_demo)]
CookieDep = Annotated[str | None, Cookie(alias=COOKIE)]


class MessageIn(BaseModel):
    """Exactly one of text, a voice note or photo (base64), or a button id (checked by
    WebMessageParser)."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, max_length=4000)
    audio_base64: str | None = None
    audio_type: str | None = Field(default=None, max_length=64)
    image_base64: str | None = None
    image_type: str | None = Field(default=None, max_length=64)
    button_id: str | None = Field(default=None, max_length=300)


@router.get("")
async def page() -> FileResponse:
    return FileResponse(PAGE, media_type="text/html", headers=SECURITY_HEADERS)


@router.get("/session")
async def session(request: Request, demo: DemoDep, cookie: CookieDep = None) -> Response:
    try:
        visitor = await demo.visitor(cookie, _client_ip(request))
    except DemoRefused as refused:
        return _refused(refused)
    response = JSONResponse({"ready": True}, headers=SECURITY_HEADERS)
    if visitor.cookie is not None:
        _set_cookie(response, request, visitor.cookie)
    return response


@router.post("/messages")
async def post_message(
    request: Request, body: MessageIn, demo: DemoDep, cookie: CookieDep = None
) -> Response:
    if not _same_origin(request):
        return _error(status.HTTP_403_FORBIDDEN, {"error": "bad_origin"})
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return _error(status.HTTP_413_CONTENT_TOO_LARGE, {"error": "too_large"})
    try:
        user_hash = demo.known_visitor(cookie)
        audio = _decoded(body.audio_base64, "audio")
        image = _decoded(body.image_base64, "image")
        message_id = await demo.submit(
            user_hash,
            _client_ip(request),
            WebUpload(
                text=body.text,
                audio=audio,
                audio_type=body.audio_type,
                button_id=body.button_id,
                image=image,
                image_type=body.image_type,
            ),
        )
    except DemoRefused as refused:
        return _refused(refused)
    except WebInputInvalid as invalid:
        return _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"error": "invalid_message", "field": invalid.field, "reason": invalid.reason},
        )
    return JSONResponse(
        {"message_id": message_id}, status_code=status.HTTP_202_ACCEPTED, headers=SECURITY_HEADERS
    )


@router.get("/messages/{message_id}")
async def get_message(message_id: str, demo: DemoDep, cookie: CookieDep = None) -> Response:
    try:
        user_hash = demo.known_visitor(cookie)
    except DemoRefused as refused:
        return _refused(refused)
    view = await demo.message_view(user_hash, message_id)
    if view is None:
        return _error(status.HTTP_404_NOT_FOUND, {"error": "not_found"})
    return JSONResponse(DemoViewSerializer.message(view), headers=SECURITY_HEADERS)


@router.get("/history")
async def history(
    demo: DemoDep,
    cookie: CookieDep = None,
    before: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=HISTORY_MAX_PAGE)] = HISTORY_PAGE,
) -> Response:
    """The visitor's conversation so far, newest page first (s14 §4.5): `before` is the
    `older_cursor` of the page already shown. Someone else's turn id is 404, like an unknown one."""
    try:
        user_hash = demo.known_visitor(cookie)
    except DemoRefused as refused:
        return _refused(refused)
    page = await demo.history(user_hash, before, limit)
    if page is None:
        return _error(status.HTTP_404_NOT_FOUND, {"error": "not_found"})
    headers = {**SECURITY_HEADERS, "Cache-Control": "no-store"}
    return JSONResponse(DemoViewSerializer.history(page), headers=headers)


@router.get("/events")
async def events(
    demo: DemoDep,
    hub: Annotated[TurnProgressHub, Depends(get_turn_progress_hub)],
    stream: Annotated[TurnEventStream, Depends(get_turn_event_stream)],
    cookie: CookieDep = None,
) -> Response:
    """The visitor's live trace (s14 §4.4): their own turns only, at most two streams each."""
    try:
        user_hash = demo.known_visitor(cookie)
        subscription = hub.open(user_hash)
    except DemoRefused as refused:
        return _refused(refused)
    headers = {**SECURITY_HEADERS, "Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(
        stream.events(subscription), media_type="text/event-stream", headers=headers
    )


@router.get("/media/{blob_id}")
async def media(
    blob_id: UUID,
    demo: DemoDep,
    blobs: Annotated[MediaBlobRepository, Depends(get_media_repository)],
    cookie: CookieDep = None,
) -> Response:
    """Reply audio and khoj cards: only the visitor's own, not expired (s14 §4.5)."""
    try:
        user_hash = demo.known_visitor(cookie)
    except DemoRefused as refused:
        return _refused(refused)
    owned = await blobs.owned(
        user_hash, blob_id, (MediaPurpose.REPLY_AUDIO, MediaPurpose.KHOJ_CARD)
    )
    if owned is None:
        return _error(status.HTTP_404_NOT_FOUND, {"error": "not_found"})
    headers = {**SECURITY_HEADERS, "Cache-Control": "private, max-age=3600"}
    return Response(content=owned.data, media_type=owned.mime_type, headers=headers)


@router.post("/reset")
async def reset(
    request: Request,
    demo: DemoDep,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    cookie: CookieDep = None,
) -> Response:
    """Delete everything about this visitor (the click is the confirmation) and the cookie."""
    if not _same_origin(request):
        return _error(status.HTTP_403_FORBIDDEN, {"error": "bad_origin"})
    try:
        user_hash = demo.known_visitor(cookie)
    except DemoRefused as refused:
        return _refused(refused)
    await users.purge_user(user_hash)
    response = Response(status_code=status.HTTP_204_NO_CONTENT, headers=SECURITY_HEADERS)
    response.delete_cookie(COOKIE, path="/demo")
    return response


# --- helpers ---------------------------------------------------------------------------------


def _decoded(encoded: str | None, field: str) -> bytes | None:
    """A base64 voice note or photo; anything that isn't base64 is refused for that field."""
    if encoded is None:
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise WebInputInvalid(field, "type_mismatch") from exc


def _same_origin(request: Request) -> bool:
    """CSRF's second layer (s14 §4.2): the Origin (or Referer) is this site's own host."""
    source = request.headers.get("origin") or request.headers.get("referer")
    if not source:
        return False
    return urlsplit(source).netloc == request.headers.get("host", "")


def _client_ip(request: Request) -> str:
    """The visitor's IP: Cloudflare's header when the request came through our local tunnel
    (cloudflared on this machine), else the socket peer. Only ever stored hashed."""
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("cf-connecting-ip")
    return forwarded if forwarded and peer in LOOPBACK else peer


def _set_cookie(response: Response, request: Request, value: str) -> None:
    response.set_cookie(
        COOKIE,
        value,
        max_age=int(SESSION_TTL.total_seconds()),
        path="/demo",
        httponly=True,
        samesite="lax",
        secure=request.headers.get("x-forwarded-proto") == "https" or request.url.scheme == "https",
    )


def _refused(refused: DemoRefused) -> Response:
    codes: dict[str, int] = {
        "no_session": status.HTTP_401_UNAUTHORIZED,
        "rate_limited": status.HTTP_429_TOO_MANY_REQUESTS,
        "stream_limit": status.HTTP_429_TOO_MANY_REQUESTS,
        "daily_budget_reached": status.HTTP_503_SERVICE_UNAVAILABLE,
    }
    body: dict[str, object] = {"error": refused.reason}
    headers = dict(SECURITY_HEADERS)
    if refused.scope is not None:
        body["scope"] = refused.scope
    if refused.retry_after_s is not None:
        body["retry_after_s"] = refused.retry_after_s
        headers["Retry-After"] = str(refused.retry_after_s)
    return JSONResponse(body, status_code=codes[refused.reason], headers=headers)


def _error(code: int, body: dict[str, object]) -> Response:
    return JSONResponse(body, status_code=code, headers=SECURITY_HEADERS)
