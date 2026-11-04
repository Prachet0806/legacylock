"""Exact origin CSRF validation; request Host never grants authority."""

from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from config import get_settings


def canonical(value):
    try:
        url = urlsplit(value)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
            return None
        return (
            url.scheme,
            url.hostname.lower(),
            url.port or (443 if url.scheme == "https" else 80),
        )
    except ValueError:
        return None


class OriginCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await call_next(request)
        settings = get_settings()
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        source = origin if origin is not None else referer
        if source is not None:
            allowed = {canonical(o.strip()) for o in settings.allowed_origins.split(",")}
            allowed.discard(None)
            if canonical(source) not in allowed or (
                origin is not None and urlsplit(origin).path not in ("", "/")
            ):
                return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
        elif settings.environment == "production" and not request.headers.get(
            "authorization", ""
        ).startswith("Bearer "):
            cookies = any(
                request.cookies.get(name)
                for name in [
                    settings.session_cookie_name_owner,
                    settings.session_cookie_name_owner_refresh,
                    settings.session_cookie_name_beneficiary,
                    settings.session_cookie_name_beneficiary_refresh,
                ]
            )
            bootstrap = request.url.path.startswith(
                ("/auth/login", "/auth/register", "/access/login", "/access/invitation")
            )
            if cookies or bootstrap:
                return JSONResponse({"detail": "Browser origin required"}, status_code=403)
        return await call_next(request)
