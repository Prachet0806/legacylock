"""Request ID middleware for correlation."""

import re
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", request_id):
            request_id = uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        from services.request_ctx import client_ip_ctx, request_id_ctx

        request_id_ctx.set(request_id)
        try:
            from services.proxy import client_ip as resolve_ip

            client_ip = resolve_ip(request)
        except Exception:
            client_ip = None
        client_ip_ctx.set(client_ip)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
