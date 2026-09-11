"""Origin check middleware — CSRF defense for cookie-authed mutations.

Browsers always send Origin (fetch) or Referer (navigation/form) on
state-changing requests. If either is present, its host must match the
configured ALLOWED_ORIGINS or the request's own host; otherwise 403.

Requests with neither header (curl, mobile apps, same-origin navigations
without Referer) pass through — API clients are unaffected. This pairs with
SameSite=Lax cookies: Lax already blocks cross-site POST cookies, this
covers the remaining cases (e.g. top-level navigations, lax-allowed GETs
with side effects — of which this API has none, defense in depth).
"""

from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from config import get_settings

_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def _allowed_hosts() -> set[str]:
    try:
        origins = [o.strip().rstrip("/") for o in get_settings().allowed_origins.split(",") if o.strip()]
    except Exception:
        origins = []
    hosts = set()
    for o in origins:
        try:
            hosts.add(urlparse(o).netloc.lower())
        except Exception:
            continue
    return hosts


class OriginCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in _UNSAFE:
            return await call_next(request)
        origin = request.headers.get("origin") or request.headers.get("referer")
        if not origin:
            return await call_next(request)
        try:
            host = urlparse(origin).netloc.lower()
        except Exception:
            return await call_next(request)
        if not host:
            return await call_next(request)
        allowed = _allowed_hosts()
        req_host = (request.headers.get("host") or "").split(",")[0].strip().lower()
        if host in allowed or (req_host and host == req_host):
            return await call_next(request)
        return JSONResponse(status_code=403, content={"detail": "Origin not allowed"})
