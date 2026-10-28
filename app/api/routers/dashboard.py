"""/status (public, admin extras) and /dashboard (admin, signed link) (s13 §4.7, §4.9).

Thin: the builders read and aggregate, the renderer escapes. `GET /dashboard?t=<token>` swaps a
15-minute link for a 2-hour HttpOnly cookie and redirects, so the token leaves the address bar.
A rejected link is a 401 page that never says which check failed; the log records a reason code
and never the token.
"""

from pathlib import Path
from typing import Annotated, Final

from fastapi import APIRouter, Cookie, Depends, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from app.api.dashboard_page_renderer import DashboardPageRenderer
from app.api.deps import get_telemetry_pages
from app.api.telemetry_pages import TelemetryPages
from app.core.errors import LinkInvalid, StoreError
from app.core.logging import get_logger
from app.telemetry.dashboard_link_codec import DashboardClaims

router = APIRouter()
logger = get_logger(__name__)

COOKIE: Final = "marg_dash"
STYLESHEET: Final = Path(__file__).resolve().parents[2] / "static" / "dashboard" / "dashboard.css"
SECURITY_HEADERS: Final = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

PagesDep = Annotated[TelemetryPages, Depends(get_telemetry_pages)]
CookieDep = Annotated[str | None, Cookie(alias=COOKIE)]


@router.get("/status")
async def status_page(pages: PagesDep, cookie: CookieDep = None) -> Response:
    try:
        report = await pages.status.build(include_admin=_is_admin(pages, cookie))
    except StoreError as exc:
        logger.exception("status_unavailable", exc_info=exc)
        return _html(DashboardPageRenderer.unavailable(), status.HTTP_503_SERVICE_UNAVAILABLE)
    return _html(DashboardPageRenderer.status(report))


@router.get("/status.json")
async def status_data(pages: PagesDep, cookie: CookieDep = None) -> Response:
    try:
        report = await pages.status.build(include_admin=_is_admin(pages, cookie))
    except StoreError as exc:
        logger.exception("status_unavailable", exc_info=exc)
        return _json({"error": "unavailable"}, status.HTTP_503_SERVICE_UNAVAILABLE)
    return _json(report.model_dump(mode="json"))


@router.get("/dashboard")
async def dashboard_page(
    request: Request, pages: PagesDep, t: str | None = None, cookie: CookieDep = None
) -> Response:
    if t is not None:
        return _swap_link_for_cookie(request, pages, t)
    if _claims(pages, cookie) is None:
        return _html(DashboardPageRenderer.link_invalid(), status.HTTP_401_UNAUTHORIZED)
    try:
        board = await pages.dashboard.build(pages.admin_floor)
    except StoreError as exc:
        logger.exception("dashboard_unavailable", exc_info=exc)
        return _html(DashboardPageRenderer.unavailable(), status.HTTP_503_SERVICE_UNAVAILABLE)
    return _html(DashboardPageRenderer.dashboard(board))


@router.get("/dashboard/data.json")
async def dashboard_data(pages: PagesDep, cookie: CookieDep = None) -> Response:
    if _claims(pages, cookie) is None:
        return _json({"error": "link_invalid"}, status.HTTP_401_UNAUTHORIZED)
    try:
        board = await pages.dashboard.build(pages.admin_floor)
    except StoreError as exc:
        logger.exception("dashboard_unavailable", exc_info=exc)
        return _json({"error": "unavailable"}, status.HTTP_503_SERVICE_UNAVAILABLE)
    return _json(board.model_dump(mode="json"))


@router.get("/dashboard/dashboard.css")
async def stylesheet() -> FileResponse:
    return FileResponse(STYLESHEET, media_type="text/css", headers=SECURITY_HEADERS)


# --- helpers ---------------------------------------------------------------------------------


def _swap_link_for_cookie(request: Request, pages: TelemetryPages, token: str) -> Response:
    try:
        claims = pages.links.read(token)
    except LinkInvalid as exc:
        logger.warning("dashboard_link_rejected", reason=str(exc))
        return _html(DashboardPageRenderer.link_invalid(), status.HTTP_401_UNAUTHORIZED)
    response = RedirectResponse(
        "/dashboard", status_code=status.HTTP_303_SEE_OTHER, headers=SECURITY_HEADERS
    )
    response.set_cookie(
        COOKIE,
        pages.links.cookie_token(claims),
        max_age=int(pages.links.cookie_ttl.total_seconds()),
        path="/",
        httponly=True,
        samesite="lax",
        secure=request.headers.get("x-forwarded-proto") == "https" or request.url.scheme == "https",
    )
    return response


def _claims(pages: TelemetryPages, cookie: str | None) -> DashboardClaims | None:
    if cookie is None:
        return None
    try:
        return pages.links.read(cookie)
    except LinkInvalid as exc:
        logger.warning("dashboard_cookie_rejected", reason=str(exc))
        return None


def _is_admin(pages: TelemetryPages, cookie: str | None) -> bool:
    claims = _claims(pages, cookie)
    return claims is not None and claims.scope == "admin"


def _html(page: str, code: int = status.HTTP_200_OK) -> HTMLResponse:
    return HTMLResponse(page, status_code=code, headers=SECURITY_HEADERS)


def _json(body: dict[str, object], code: int = status.HTTP_200_OK) -> JSONResponse:
    return JSONResponse(body, status_code=code, headers=SECURITY_HEADERS)
