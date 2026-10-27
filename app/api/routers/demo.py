"""The web demo (s14; exception E2): a page, a session, messages in, and polling for the reply.

Thin, like the webhook: the WebDemoIngestor does the checks and the inbox insert; the worker
runs the same pipeline as for WhatsApp. Messages are JSON (a voice note as base64), so there's no
form-parsing dependency. Every response under /demo carries the security headers of s14 §4.10.
"""

import base64
import binascii
from pathlib import Path
from typing import Annotated, Final
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_media_repository, get_user_repository, get_web_demo
from app.api.web_demo_ingestor import SESSION_TTL, WebDemoIngestor
from app.channels.web.web_message_parser import WebUpload
from app.core.errors import DemoRefused, WebInputInvalid
from app.core.logging import get_logger
from app.domain.enums import MediaPurpose
from app.store.repositories.demo_repository import MessageView
from app.store.repositories.media_blob_repository import MediaBlobRepository
from app.store.repositories.user_repository import UserRepository

router = APIRouter(prefix="/demo")
logger = get_logger(__name__)

PAGE: Final = Path(__file__).resolve().parents[2] / "static" / "demo" / "index.html"
COOKIE: Final = "marg_session"
MAX_BODY_BYTES: Final = 1_500_000  # a 1 MB voice note as base64, plus a little
SECURITY_HEADERS: Final = {
    "Content-Security-Policy": (
        "default-src 'self'; media-src 'self' blob:; connect-src 'self'; img-src 'self' data:; "
        "style-src 'self'; script-src 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}
LOOPBACK: Final = frozenset({"127.0.0.1", "::1"})

DemoDep = Annotated[WebDemoIngestor, Depends(get_web_demo)]
CookieDep = Annotated[str | None, Cookie(alias=COOKIE)]


class MessageIn(BaseModel):
    """Exactly one of text, a voice note (base64) or a button id (checked by WebMessageParser)."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, max_length=4000)
    audio_base64: str | None = None
    audio_type: str | None = Field(default=None, max_length=64)
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
        audio = _decoded_audio(body.audio_base64)
        message_id = await demo.submit(
            user_hash,
            _client_ip(request),
            WebUpload(
                text=body.text,
                audio=audio,
                audio_type=body.audio_type,
                button_id=body.button_id,
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
    return JSONResponse(_message_json(view), headers=SECURITY_HEADERS)


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


def _message_json(view: MessageView) -> dict[str, object]:
    turn = view.turn
    if turn is None:
        return {"status": view.message_status, "turn": None}
    return {
        "status": view.message_status,
        "turn": {
            "turn_id": str(turn.turn_id),
            "status": turn.status,
            "route": turn.route,
            "steps": [
                {
                    "step": step.step,
                    "outcome": step.outcome,
                    "duration_ms": step.duration_ms,
                    "detail": step.detail,
                    "cost_usd": str(step.cost_usd) if step.cost_usd is not None else None,
                }
                for step in turn.steps
            ],
            "parts": [
                {
                    "kind": part.kind,
                    "text": part.text,
                    "buttons": [{"id": b.id, "title": b.title} for b in part.buttons],
                    "audio_url": f"/demo/media/{part.audio_blob_id}"
                    if part.audio_blob_id
                    else None,
                    "image_url": f"/demo/media/{part.image_blob_id}"
                    if part.image_blob_id
                    else None,
                }
                for part in turn.parts
            ],
        },
    }


def _decoded_audio(encoded: str | None) -> bytes | None:
    if encoded is None:
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise WebInputInvalid("audio", "type_mismatch") from exc


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
